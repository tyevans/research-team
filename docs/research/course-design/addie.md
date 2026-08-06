# ADDIE: The Instructional Systems Design Workflow As Practiced

**Scope.** This document describes how ADDIE actually operates in corporate L&D and higher-ed instructional design teams today (2025-2026), with emphasis on named artifacts, decision sequence, handling of unstructured source material, and review gates. It closes with mechanization notes for modeling ADDIE as a multi-agent pipeline.

---

## 0. What ADDIE Is and Is Not

ADDIE is not a single authored methodology. It is a *generic label* for the family of Instructional Systems Design (ISD) processes that descend from US military training design work of the 1970s, later formalized at Florida State University. There is no canonical ADDIE spec, no ADDIE certification body, and no agreed artifact list. What exists is a five-phase vocabulary — **Analysis, Design, Development, Implementation, Evaluation** — that practitioners use as a shared frame while filling in their own house process.

This matters for mechanization: **ADDIE describes a dependency order, not a procedure.** The real procedure lives in the artifacts that teams pass between phases. Those artifacts are far more standardized across the industry than the phase definitions are. Design a pipeline around the artifacts, not around the five words.

Current practice ([Research.com](https://research.com/education/the-addie-model), [D2L](https://www.d2l.com/blog/what-is-the-addie-model-of-instructional-design/)) is near-universally *adapted* ADDIE — phases overlap, evaluation runs continuously, and iteration loops back from Development into Design. Pure sequential ADDIE ("waterfall ADDIE") is mostly a straw man in discourse and a real practice only in regulated, high-documentation environments (defense, pharma, aviation, compliance training) where the sign-off trail is itself a deliverable.

---

## 1. Analysis

**Purpose.** Determine whether instruction is the right intervention at all, and if so, for whom, about what, and under what constraints.

**Trigger.** A stakeholder request, typically vague and already solution-shaped ("we need a course on the new CRM"). The first job of Analysis is to refuse the premise long enough to test it.

### 1.1 Sub-analyses (each produces its own artifact)

| Sub-analysis | Question answered | Artifact |
|---|---|---|
| **Needs analysis / TNA** (Training Needs Assessment) | Is there a performance problem, and is a lack of knowledge/skill its cause? | **Needs Analysis Report** |
| **Gap analysis** | What is the delta between current and desired performance, stated measurably? | **Performance Gap Statement** (current state / desired state / gap / business metric affected) |
| **Audience / learner analysis** | Who learns this? Prior knowledge, roles, literacy, language, accessibility needs, motivation, tenure distribution, headcount | **Learner Profile** / **Audience Persona Set** |
| **Task analysis** (a.k.a. job-task analysis, procedural analysis) | What does a competent performer actually *do*, step by step? | **Task Inventory** and **Hierarchical Task Analysis (HTA)** |
| **Content analysis** | What facts, concepts, principles, procedures underlie those tasks? | **Content Outline** / **Topic Map** |
| **Context / environment analysis** | Where is the learning consumed and where is the performance executed? Devices, bandwidth, shift patterns, floor noise, LMS version, SCORM/xAPI support | **Constraints Register** |
| **Extant data review** | What already exists — SOPs, prior decks, help center, incident logs, QA scores | **Source Inventory** |

Two analyses do the heaviest lifting and are the most frequently skipped: gap analysis and task analysis. Devlin Peck's survey of practice is blunt that "organizations and instructional designers alike fail to conduct proper analysis and evaluation" ([Devlin Peck](https://www.devlinpeck.com/content/addie-instructional-design)).

### 1.2 Task analysis mechanics

Task analysis is the step that converts expertise into structure. Three techniques dominate:

- **Hierarchical task analysis** — decompose a goal into subtasks and operations, with *plans* stating the conditions under which each subtask fires. Produces a tree.
- **Procedural / linear analysis** — ordered step list with decision points. Produces a flow.
- **Cognitive task analysis (CTA)** — targets the *judgment* an expert applies, not the observable steps. Used for troubleshooting, diagnosis, negotiation, anything where the hard part is knowing which rule applies. Critical-decision-method interviews are the standard elicitation technique.

CTA exists because of a known and well-documented failure of naive elicitation: **experts omit internalized steps.** Practitioners report that experts "have performed the task so often that some of the steps become so internalized that they fail to acknowledge doing so" ([Foundations of Instructional Design](https://id.rjhogue.name/foundations/chapter/task-analysis-skills-and-knowledge-analysis/)). An expert-authored procedure is systematically incomplete at exactly the points a novice will fail.

### 1.3 Where unstructured research enters

Analysis is where the bulk of raw source material lands. Typical inbound:

- **SME interview recordings and transcripts** (1-3 SMEs, 45-90 min each, often several rounds)
- **Existing artifacts**: SOPs, policy PDFs, prior slide decks, job aids, product documentation, release notes, help center articles
- **The "content dump"** — the SME's shared drive folder, delivered in lieu of an interview
- **Performance data**: QA scorecards, support ticket categories, error/incident logs, sales metrics, audit findings
- **Observation notes** from job shadowing or call listening
- **Learner voice**: focus groups, surveys, exit interviews, prior course feedback

The standard SME interview opener across the practitioner literature is to ask the SME to walk the process step by step, captured live on a whiteboard or shared doc, then to ask of each step: *what must the learner know*, and *what must the learner be able to do* ([The eLearning Coach](https://theelearningcoach.com/elearning_design/subject-matter-experts/)). This is deliberately a structure-first, prose-second protocol — it exists because SMEs default to unbounded explanation. The known pathology is that "it's difficult for experts to minimize information — they know so much."

**Processing pipeline for source material (as practiced):**

1. Transcribe (now near-universally automated).
2. Tag/extract by type: step, rule, exception, example, war story, tool, artifact, failure mode.
3. Reconcile across sources — SMEs contradict each other and contradict the SOP. Contradictions become open questions, not silently resolved.
4. Cull against the gap statement. Anything that does not close the performance gap is cut or demoted to a reference/job-aid appendix. This is the single highest-leverage editorial act in the whole model.
5. Route residue: nice-to-know content becomes a **Job Aid** or **Resource Library entry**, not a lesson.

Cathy Moore's **Action Mapping** is the dominant discipline used at this boundary: start from the business metric, list what people must *do* differently, and admit content only where lack of knowledge is the actual barrier. It exists specifically to kill content-dump-driven courses.

### 1.4 Analysis outputs (the phase deliverable)

Bundled as an **Analysis Report** or **Project Charter / Training Plan**:

- Business goal and target metric
- Performance gap statement
- Recommendation: training / non-training intervention / hybrid (a legitimate Analysis output is "do not build a course")
- Learner profile(s)
- Task inventory with criticality/frequency/difficulty ratings
- Terminal and enabling **learning objectives** (draft) — sometimes deferred to Design
- Delivery modality recommendation (ILT, VILT, eLearning, blended, microlearning, coaching, job aid)
- Constraints: budget, deadline, LMS, accessibility (WCAG 2.1 AA / Section 508), localization targets, SME availability hours
- Evaluation strategy at the Kirkpatrick level the org will actually fund
- Open questions / assumptions register
- RACI and review schedule

### 1.5 Gate

**Analysis sign-off** by the project sponsor (budget holder) and the lead SME. Signs off on: scope, modality, seat-time estimate, budget, and the objective set. This is the cheapest place to say no and the most expensive gate to skip.

---

## 2. Design

**Purpose.** Decide *what the learning experience is* without yet building it. Design is a paper phase; its output is a blueprint precise enough that a different person could build from it.

### 2.1 Decisions made, in order

1. **Finalize learning objectives.** Terminal objectives (course-level) decomposed into enabling objectives (module/lesson-level). Written as observable, measurable behaviors with condition and criterion — the ABCD convention (Audience, Behavior, Condition, Degree) is standard, and verbs are chosen against **Bloom's revised taxonomy** so cognitive level is explicit and testable. "Understand" is rejected; "classify," "troubleshoot," "calculate to within 2%" are accepted.
2. **Sequence.** Order objectives — hierarchical (prerequisite-first, per Gagné's learning hierarchies), chronological (mirror the real workflow), whole-to-part, or simple-to-complex/elaboration.
3. **Chunk.** Map objectives to modules and lessons; set durations. This produces the **course map**.
4. **Assessment strategy first** (backward design discipline): for each terminal objective, decide the evidence of mastery *before* designing instruction. Produces the **Assessment Plan** / **Assessment Blueprint** — an objective-to-item mapping table with item counts, item types, mastery cut score, remediation and retake rules.
5. **Instructional strategy per objective.** Scenario, worked example, guided practice, simulation, case study, discussion, drill. Frequently structured on Gagné's Nine Events, Merrill's First Principles, or 4C/ID for complex skills.
6. **Media and modality per chunk.** Video, interactive, text+graphic, live practice — with cost implications made explicit.
7. **Look and feel.** Visual design direction, interaction patterns, navigation model, accessibility approach.
8. **Technical design.** Authoring tool (Storyline, Rise, Captivate, Lectora), tracking standard (SCORM 1.2 / 2004 / xAPI / cmi5), LMS/LXP target, completion and pass conditions.

### 2.2 Artifacts

- **Design Document** (a.k.a. **Course Design Document**, **CDD**, **Learning Design Blueprint**, **High-Level Design / HLD**) — the master contract for the phase. Contains: audience, objectives, course map, module-by-module treatment, assessment plan, media list, seat time, tone/voice guidance, accessibility and localization plan, tracking spec, assumptions.
- **Course Map / Curriculum Map** — objective-to-module matrix.
- **Assessment Blueprint** — objective-to-item mapping with cut scores.
- **Storyboard** — the screen-level or scene-level build spec. Per screen/slide: screen ID, objective reference, on-screen text, narration/VO script, visual description or asset reference, interaction specification, feedback text for each response branch, branching/navigation logic, developer notes, accessibility alt text. Delivered as Word/Google Doc tables, PowerPoint, Excel, or in-tool (Rise/Storyline outlines).
- **Prototype** — a functioning slice, typically 1-3 representative screens or one full module, built to settle look-and-feel and interaction arguments before mass production. Industry guidance is explicit that Design should produce "a storyboard or design document detailed enough that someone else could build the course from it," and lists storyboard creation, UI/UX design, prototype creation, and visual design as discrete Design steps ([InstructionalDesign.org](https://www.instructionaldesign.org/models/addie/), [Devlin Peck](https://www.devlinpeck.com/content/addie-instructional-design)).
- **Style Guide** — terminology, tone, capitalization, brand, accessibility rules.
- **Script** — for video/animation tracks, split out from the storyboard.
- For ILT: **Facilitator Guide outline** and **Participant Workbook outline**.

### 2.3 Gates

Design carries the two highest-value sign-offs in the model, because everything downstream is expensive to change:

- **Design Document sign-off** — sponsor + SME + (often) legal/compliance. Locks scope, objectives, seat time, module count.
- **Storyboard sign-off** — SME (content accuracy) + sponsor (scope). Industry practice treats this as the content-accuracy gate: "the content itself should have already been signed off on the Storyboard" before build begins ([Thinkdom](https://www.thinkdom.co/post/exploring-alpha-beta-gold-stages-in-elearning-content-development)). Change requests after this point are formally treated as scope changes.
- **Prototype / look-and-feel sign-off** — sponsor + brand.

---

## 3. Development

**Purpose.** Build the thing the storyboard specifies. This is production, not design — though in practice it is where unresolved design decisions surface and get kicked back.

### 3.1 Work

- Asset production: graphics, illustration, icons, photography, video shoot and edit, animation, screen recordings, VO recording (scratch first, then talent), music/SFX.
- Authoring: build screens in the authoring tool, wire interactions, states, variables, branching.
- Assessment build: item authoring, question banks, randomization, scoring, feedback text.
- Tracking: SCORM/xAPI packaging, completion/success conditions, bookmarking, resume behavior.
- Accessibility build: alt text, keyboard navigation, focus order, captions, transcripts, color contrast, screen reader testing.
- Localization prep: string extraction, VO scripts to translation, layout expansion allowance.
- ILT materials: **Facilitator Guide** (timings, talk track, transition cues, activity setup, debrief questions, answer keys, troubleshooting), **Participant Workbook**, **slide deck**, **activity/handout kits**, **exercise data sets**.
- QA: functional testing (all paths, all devices, all browsers), content proofing, LMS smoke test, link checking.

### 3.2 Alpha / Beta / Gold — the actual review ladder

Development is structured around three named builds. This is the most operationally concrete convention in the whole field and it is essentially universal in vendor and agency work ([eLearning Industry](https://elearningindustry.com/what-are-alpha-beta-gold-stages-in-elearning-content-development), [Omniplex](https://omniplexlearning.com/blog/the-abcs-of-the-elearning-content-development-stages/)).

| Build | Contents | Reviewed by | What the review is *for* |
|---|---|---|---|
| **Alpha** | First complete, playable version. All storyboard content in place, all interactions functional. Placeholder or scratch assets acceptable (scratch VO, temp images), but guidance is to make it as complete as possible including multimedia and interactivity. | Client/sponsor + SME + QA | Content accuracy, completeness, instructional soundness, functional correctness. This is the substantive-feedback round. |
| **Beta** | Alpha feedback implemented. Final or near-final assets — real VO, final images/video. Polished. | Client/sponsor + SME | Verification that alpha changes landed. Explicitly the last look before sign-off — remaining changes are expected to be minor/cosmetic only. |
| **Gold** | Beta feedback implemented, packaged, deployed to the real LMS and tested end-to-end there. | Client/sponsor, LMS admin | Final sign-off; release readiness. |

Each stage carries a formal sign-off, typically from the client or the SME accountable for the learning project. Teams that allow substantive content change at Beta or Gold are, in practice, teams whose Storyboard gate failed.

Parallel to this: **pilot / formative tryout** — one-to-one tryout with 2-3 representative learners, then small-group tryout, then field trial. Classic ISD prescribes all three; most teams run one, and many run none.

### 3.3 Artifacts

Alpha build, Beta build, Gold build, asset library, QA test plan and defect log, review-comment log with dispositions, SCORM/xAPI package, facilitator guide, participant workbook, job aids, LMS metadata (title, description, duration, tags, prerequisites, completion rules), accessibility conformance report (VPAT where required).

---

## 4. Implementation

**Purpose.** Get the intervention in front of learners and make it survivable in the real environment.

### 4.1 Work

- **Deploy**: upload package to LMS, configure completion/pass rules, set up curriculum/learning path, assignment rules and audiences, due dates, reminders, certificates, CEU/CPE credit.
- **Pilot cohort** run and hotfix window.
- **Train-the-trainer** for ILT/VILT — facilitators trained on curriculum, outcomes, delivery method, and the assessment; classic ADDIE calls this out as an explicit Implementation task ([InstructionalDesign.org](https://www.instructionaldesign.org/models/addie/)).
- **Learner readiness**: registration, access, tool orientation, prerequisite communications.
- **Logistics** for live delivery: rooms, platform, equipment, materials printing, rosters.
- **Communication plan / launch campaign**: manager briefing pack, announcement emails, intranet post.
- **Manager enablement**: the reinforcement layer. Level 3 behavior change does not occur without manager involvement; a manager briefing and coaching guide is the standard lever.
- **Support**: help desk runbook, known-issues list, escalation path.
- **Data plumbing**: confirm tracking fires correctly, dashboards populate, xAPI statements land in the LRS.

### 4.2 Artifacts

Deployment checklist, LMS configuration record, pilot report, train-the-trainer deck and certification record, launch communications kit, manager briefing/reinforcement guide, support runbook, roster/enrollment plan, hotfix log.

### 4.3 Gate

**Go/no-go for full launch**, following the pilot. Owners: sponsor, LMS admin, support lead.

---

## 5. Evaluation

**Purpose.** Determine whether the intervention worked, and feed that back.

### 5.1 Formative vs summative

- **Formative evaluation runs throughout all five phases** — it is the review activity embedded in every gate: storyboard review, alpha/beta review, one-to-one and small-group tryouts, pilot. In doctrine, formative evaluation is not a phase-five activity; it is what makes the arrows go backward.
- **Summative evaluation** happens after implementation: criterion-referenced testing against the stated objectives, plus stakeholder and learner feedback, plus downstream performance data.

### 5.2 The Kirkpatrick levels (the operative vocabulary)

| Level | Question | Instruments | When |
|---|---|---|---|
| **1 — Reaction** | Did learners find it relevant, engaging, useful? | Post-course survey ("smile sheet"), NPS, pulse items. New World Kirkpatrick adds *engagement*, *relevance*, and *customer satisfaction* as sub-dimensions. | Immediately |
| **2 — Learning** | Did knowledge/skill/confidence/commitment increase? | Pre/post assessment, criterion-referenced test, skills observation, simulation scoring, self-efficacy items | Immediately / short delay |
| **3 — Behavior** | Are they doing it differently on the job? | Manager observation, QA scores, 360 follow-up, system telemetry, self-report at 30/60/90 days. New World Kirkpatrick adds **required drivers** — the reinforcement, monitoring, and reward system that makes transfer happen. | 30-90+ days |
| **4 — Results** | Did the business metric move? | The metric named in the gap statement: error rate, cycle time, CSAT, safety incidents, sales, attrition, audit findings | 3-12 months |

Practice reality: most organizations measure Level 1 and Level 2 and stop, because Levels 3 and 4 require per-person joins across HR, LMS, and business systems that nobody owns. This is the single most cited criticism of evaluation in the field ([Devlin Peck](https://www.devlinpeck.com/content/kirkpatrick-model-evaluation), [Learning Guild](https://www.learningguild.com/articles/2529/buzzword-decoder-kirkpatrick-levels-of-evaluation/)).

**Extensions in use:**
- **Phillips ROI (Level 5)** — isolates the training effect, converts benefit to currency, and computes (net benefit / cost) as a percentage ([Valamis](https://www.valamis.com/hub/kirkpatrick-model)).
- **New World Kirkpatrick (2016)** — prefers **Return on Expectations (ROE)** and *contributive* ROI, on the grounds that training contributes to outcomes alongside other factors rather than solely causing them. Also introduces the "plan backward from Level 4" discipline: decide Level 4 evidence during Analysis, not after launch.
- **CIRO** (front-end context evaluation), **Brinkerhoff's Success Case Method** (find the extreme successes and failures and interview them — cheap, qualitative, credible), **Kaufman's five levels** (adds societal impact).

### 5.3 Artifacts

Evaluation plan (written in Analysis, executed here), Level 1 survey instrument and results, assessment item analysis (difficulty, discrimination, distractor performance), Level 3 follow-up protocol and findings, Level 4 business-impact analysis, ROI/ROE calculation, **Evaluation Report** with recommendations, and a **revision backlog** feeding the next cycle.

### 5.4 Gate

**Evaluation review** with the sponsor: continue / revise / retire the course. Courses without a retirement decision accumulate into unmaintained catalog debt.

---

## 6. Variants: SAM, Agile ID, LLAMA

### 6.1 Why variants exist

The criticisms of waterfall ADDIE are specific and well-rehearsed:

1. **Latency.** Sequential completion means the audience waits. Projects "take an excessive amount of time to reach their intended audience," and effectiveness is evaluated too late to act on ([eLearning Industry](https://elearningindustry.com/sam-successive-approximation-model-for-rapid-instructional-design)).
2. **Late feedback.** Stakeholders cannot evaluate a design document the way they can evaluate a working screen. Sign-off on paper produces confident approval of things nobody actually understood, and the disagreement surfaces at Alpha, when rework is expensive.
3. **Brittleness to change.** Requirements, products, and org priorities move faster than a 6-month build.
4. **Rigidity.** Widely characterized as "rigid and too linear."
5. **Analysis and evaluation get cut anyway.** The phases most distinctive to ADDIE are the first to be sacrificed to deadline, leaving a content-production process wearing an ISD label.
6. **Documentation-as-deliverable.** In heavy implementations the artifacts become the product; effort flows to the design document rather than the learning.

### 6.2 SAM (Successive Approximation Model, Michael Allen / Allen Interactions)

**SAM1** (small projects): a repeating three-step loop — *Evaluate → Design → Develop* — cycled three times, with the deliverable maturing each pass.

**SAM2** (larger projects), three phases:

1. **Preparation** — background information gathering, then the **Savvy Start**: a short, intense, cross-functional kickoff (sponsor, SME, designer, developer, sample learners) that rapidly rotates through design ideas and produces *sketches and rough storyboards* — deliberately unpolished, deliberately plural. The rule of thumb is three candidate designs per content area, to prevent premature commitment to the first idea.
2. **Iterative Design** — project planning (timeline, budget, task assignment) plus additional design cycles converging on a **design proof**.
3. **Iterative Development** — cycles of *Develop → Implement → Evaluate*, producing **Alpha → Beta → Gold** releases. The defining claim: at every stage there is "always something usable that learners can use and interact with."

Note that Alpha/Beta/Gold is shared vocabulary between ADDIE-as-practiced and SAM — the difference is not the build ladder but how much design is settled on paper before the first build exists.

### 6.3 Agile Instructional Design / LLAMA

**Agile ID** organizes work into 1-4 week sprints, each producing a small functional piece of the whole, with a backlog, review, and retrospective per sprint ([Cognota](https://cognota.com/blog/what-is-agile-instructional-design-methodology/), [CommLab](https://www.commlabindia.com/blog/agile-instructional-design-sprints)). Kanban variants replace sprints with WIP limits, which suits L&D teams doing continuous intake rather than discrete projects.

**LLAMA** (Lot Like Agile Management Approach, Megan Torrance) is the most concrete L&D-specific agile framing: iterative cycles, continuous review, explicit accommodation of changing business needs, and it explicitly incorporates ADDIE's analysis discipline plus Cathy Moore's **Action Mapping** for scoping.

**Agile-ADDIE reconciliation** — the mainstream position. ADDIE supplies the *dependency logic* (you cannot write objectives before you know the gap; you cannot storyboard before you have objectives); agile supplies the *cadence* (run those dependencies over a small slice, repeatedly, rather than over the whole course once). Practically: do Analysis once and thoroughly up front, then iterate D-D-I-E per module.

**Universal caveat across all variants:** scope creep is the shared enemy, and the mitigation is the same everywhere — agree in advance what constitutes a completable unit of design work (a module, a scenario cluster, a topic area) and defend that boundary. Agile ID also requires an environment that supplies rapid feedback; where stakeholders review on a two-week lag, iteration collapses and a gated model is genuinely the better fit ([AIHR](https://www.aihr.com/blog/addie-vs-sam/)).

---

## 7. Common Failure Modes

**Analysis**
- Accepting the stakeholder's solution ("build a course") as the requirement; never testing whether the cause is knowledge, motivation, tooling, process, or incentive. The most common single failure in the field.
- No measurable gap statement, so Level 3/4 evaluation is impossible by construction and the project can never be shown to have failed.
- Task analysis skipped; content analysis substituted for it. Produces courses that describe a system instead of teaching a job.
- Expert blind spot: SME-authored procedures omit internalized steps, so novices fail at gaps the course does not know exist.
- Single-SME dependency; no reconciliation across sources, so the course inherits one person's idiosyncratic practice as canon.

**Design**
- Objectives written with unobservable verbs ("understand," "be aware of," "appreciate"), making assessment arbitrary.
- Objectives derived from available content rather than from required performance — content-driven rather than outcome-driven design.
- Assessment designed after instruction, so items test recall of what was said rather than the objective's actual behavior.
- Design document approved by stakeholders who cannot read one. Approval is real; agreement is not.
- Coverage bias: everything the SME supplied gets a module, seat time balloons, and the critical 20% is diluted.
- Storyboard too thin to build from, pushing design decisions into Development where they are made by whoever is fastest.

**Development**
- Substantive content change requested at Beta or Gold — a Storyboard-gate failure surfacing late and expensively.
- Endless review loops with no round limit, no consolidated comment log, and contradictory reviewers with no tiebreaker.
- Accessibility and localization retrofitted rather than designed in.
- Media production consuming the budget that formative tryout needed.
- No pilot with real learners; internal reviewers substitute for the target audience.

**Implementation**
- Launch without manager enablement, guaranteeing no transfer and therefore no Level 3 movement.
- LMS/tracking misconfiguration discovered after launch; completions do not record.
- Mandatory-assignment blast with no communication of relevance, producing compliance clicking.
- No support runbook; the first defect becomes a credibility event.

**Evaluation**
- Level 1 only, treated as effectiveness data. Satisfaction correlates weakly with learning and near-zero with behavior change.
- Evaluation designed after launch, when the pre-measure no longer exists and the counterfactual is gone.
- No revision loop: findings are reported and nothing is changed.
- No retirement decision; catalog fills with stale, unowned, still-mandatory courses.

**Process-level**
- Documentation becomes the deliverable; the artifacts get the care the learning needed.
- SME availability assumed rather than contracted, so the critical path is a person with a day job.
- The five phases treated as strictly sequential when the org cannot support the latency, producing an ADDIE-labeled process where Analysis and Evaluation are ceremonial.

---

## 8. Mechanization Notes

Modeling ADDIE as a discrete-step automated multi-agent pipeline. Each step is specified as **inputs → outputs (named artifacts) → judgment required → human review gate.**

Two structural notes first:

- **The artifacts are the interface, not the phases.** Design each step to emit a named, schema'd artifact. The phase boundaries are useful only as dependency edges.
- **The pipeline should be re-entrant per module, not per course.** Run Analysis once at course scope; run Design/Development/Evaluation per module. This is the agile-ADDIE reconciliation, and it also bounds blast radius when a step produces bad output.

### Step A1 — Intake & Gap Framing

- **Inputs:** stakeholder request (free text), business context, any named metric, org constraints.
- **Outputs:** `PerformanceGapStatement` (current state, desired state, measurable gap, business metric, hypothesized causes), `InterventionRecommendation` (training / non-training / hybrid, with rationale), `OpenQuestions[]`.
- **Judgment:** Is the cause a knowledge/skill deficit at all, versus process, tooling, incentive, or staffing? This is a causal inference from thin evidence and it is the judgment most consequential to everything downstream.
- **Human reviews before proceeding:** the gap statement and the recommendation. Non-negotiable gate — an automated pipeline's strongest bias is toward producing a course, since that is what it makes. A human must be able to answer "no course."

### Step A2 — Source Ingestion & Normalization

- **Inputs:** SME transcripts, SOPs, decks, PDFs, help-center exports, tickets, QA scorecards, recordings.
- **Outputs:** `SourceInventory` (per-source: id, type, author, date, authority level, coverage), `NormalizedClaimSet` (atomized statements, each with source citation and type tag: step / rule / exception / example / constraint / rationale / tool), `ContradictionLog` (conflicting claims across sources, unresolved).
- **Judgment:** Source authority ranking (SOP vs. SME opinion vs. undocumented practice); recency; what counts as one atomic claim.
- **Human reviews:** the `ContradictionLog`. Do not auto-resolve contradictions — route each to a named SME for adjudication. Silent resolution is how a pipeline manufactures confidently wrong canon.

### Step A3 — Audience & Constraints Analysis

- **Inputs:** HR/role data, stakeholder input, prior course feedback, technical environment facts.
- **Outputs:** `LearnerProfile[]` (role, prior knowledge, headcount, accessibility needs, language, device/context), `ConstraintsRegister` (LMS, tracking standard, budget, deadline, seat-time ceiling, accessibility target, localization targets, SME hours available).
- **Judgment:** Where the prior-knowledge floor sits; which learner segments are distinct enough to need differentiated treatment.
- **Human reviews:** learner profiles (easy to hallucinate a plausible-but-wrong audience) and the seat-time ceiling.

### Step A4 — Task & Content Analysis

- **Inputs:** `NormalizedClaimSet`, `LearnerProfile[]`, `PerformanceGapStatement`.
- **Outputs:** `TaskInventory` (task, criticality, frequency, difficulty, current error rate), `HierarchicalTaskAnalysis` (tree with conditional plans), `ContentMap` (concepts/facts/principles supporting each task), `ExpertGapFlags[]` (steps suspected omitted as internalized — points where the HTA jumps abstraction levels or a decision has no stated criterion).
- **Judgment:** Decomposition granularity; criticality rating; detecting the expert blind spot. `ExpertGapFlags` is the highest-value automated contribution in the whole pipeline — machine detection of *where an expert stopped explaining* is tractable (unstated decision criteria, abrupt abstraction jumps, unexplained jargon) and is exactly what human designers miss.
- **Human reviews:** the HTA, with a SME, and every `ExpertGapFlag` resolved or dismissed explicitly.

### Step A5 — Scope Culling (Action Mapping)

- **Inputs:** `TaskInventory`, `ContentMap`, `PerformanceGapStatement`, seat-time ceiling.
- **Outputs:** `InScopeTaskSet`, `OutOfScopeRegister` (with disposition: cut / job aid / reference library / separate course), `JobAidSpec[]`.
- **Judgment:** Does closing this task's gap move the named metric? Would a job aid outperform instruction here? This is the discipline that prevents content-dump courses and it is adversarial to the pipeline's own inclination to cover everything supplied.
- **Human reviews:** the cut list, explicitly. Reviewing what was *removed* is more informative than reviewing what was kept, and cuts are what SMEs contest.

### Step D1 — Objective Formulation

- **Inputs:** `InScopeTaskSet`, `LearnerProfile[]`.
- **Outputs:** `TerminalObjective[]` and `EnablingObjective[]` (each: ABCD-structured, Bloom level tagged, parent task reference, assessability flag).
- **Judgment:** Correct Bloom level for the real job demand (over-leveling inflates cost, under-leveling produces courses that teach recall for a judgment task); verb observability.
- **Human reviews:** the objective set — this is the contract everything downstream is measured against. Auto-reject unobservable verbs before human review rather than spending human attention on them.

### Step D2 — Assessment Design (before instruction, deliberately)

- **Inputs:** `TerminalObjective[]`, `EnablingObjective[]`, `ConstraintsRegister`.
- **Outputs:** `AssessmentBlueprint` (objective → item type → item count → cognitive level → mastery criterion), `AssessmentItem[]` (stem, options, key, distractor rationale, feedback per option, objective ref), `MasteryRules` (cut score, retakes, remediation routing).
- **Judgment:** Whether the item actually elicits the objective's behavior rather than recall of its wording; distractor plausibility (good distractors encode real misconceptions, which should come from `ExpertGapFlags` and error data).
- **Human reviews:** item-to-objective alignment and answer keys, by a SME. Assessment is the artifact where an error is both most likely and most damaging — a wrong key teaches the wrong thing and is defended by the system.

### Step D3 — Structure & Sequencing

- **Inputs:** objectives, `HierarchicalTaskAnalysis`, constraints.
- **Outputs:** `CourseMap` (modules, lessons, objective assignments, durations, prerequisites), `SequencingRationale`.
- **Judgment:** Sequencing principle selection (prerequisite / chronological / simple-to-complex); chunk sizing against cognitive load and attention.
- **Human reviews:** module boundaries and total seat time against the ceiling.

### Step D4 — Instructional Strategy & Treatment

- **Inputs:** `CourseMap`, objectives, `LearnerProfile[]`, `ConstraintsRegister`, `NormalizedClaimSet`.
- **Outputs:** `DesignDocument` (the master blueprint), `TreatmentSpec[]` per module (strategy, media, interaction pattern, practice design), `StyleGuide`.
- **Judgment:** Strategy fit to cognitive level and job context; realistic scenario construction (needs authentic detail from source material, which is why `NormalizedClaimSet` must remain available this far downstream); cost/benefit of media choices.
- **Human reviews:** the `DesignDocument`, as a formal sign-off gate with sponsor and SME. Recommendation: force review of a **prototype module** alongside the document rather than the document alone — the well-documented failure of paper sign-off is that stakeholders approve documents they cannot evaluate.

### Step D5 — Storyboarding

- **Inputs:** `DesignDocument`, `TreatmentSpec[]`, `NormalizedClaimSet`, `StyleGuide`, `AssessmentItem[]`.
- **Outputs:** `Storyboard` — per screen: `screen_id`, `objective_ref`, `on_screen_text`, `narration_script`, `visual_spec` (or asset ref), `interaction_spec`, `feedback_branches[]`, `navigation_logic`, `alt_text`, `source_citations[]`, `developer_notes`.
- **Judgment:** Narration/on-screen-text redundancy discipline; interaction that produces practice rather than clicking; feedback that corrects the misconception rather than announcing wrongness.
- **Human reviews:** **Content-accuracy sign-off by SME.** The single most important gate. Every factual claim on a screen should carry a `source_citation` back to `NormalizedClaimSet` so review is verification rather than trust — this is where an automated pipeline can beat human practice, since human storyboards rarely carry provenance.

### Step V1 — Development / Build

- **Inputs:** `Storyboard`, `StyleGuide`, asset library, `ConstraintsRegister`.
- **Outputs:** `AlphaBuild`, `BetaBuild`, `GoldBuild`, `AssetLibrary`, `QATestPlan`, `DefectLog`, `ReviewCommentLog` (with per-comment disposition), `TrackingPackage` (SCORM/xAPI/cmi5), `AccessibilityConformanceReport`, and for ILT `FacilitatorGuide` + `ParticipantWorkbook`.
- **Judgment:** Mostly craft and QA rather than instructional judgment; the real judgment is triage — which review comments are in scope, which are scope changes, which are contradictory and need escalation.
- **Human reviews:** Alpha (substantive: content, function, instructional soundness), Beta (verification only), Gold (release readiness on the real LMS). Preserve the three-gate ladder even in an automated pipeline — its value is that it *declines* substantive change late, which is the discipline automation will otherwise erode by making change look cheap.
- **Additionally required:** a **formative tryout with 2-3 real learners** between Alpha and Beta. This is the step most often skipped in human practice and the one an automated pipeline cannot substitute for, because it is the only source of evidence about actual novices.

### Step I1 — Implementation

- **Inputs:** `GoldBuild`, `TrackingPackage`, `LearnerProfile[]`, `EvaluationPlan`.
- **Outputs:** `DeploymentChecklist`, `LMSConfigurationRecord` (completion rules, assignment audiences, due dates, prerequisites), `LaunchCommunicationsKit`, `ManagerReinforcementGuide`, `SupportRunbook`, `PilotReport`, `TrainTheTrainerKit` (if facilitated).
- **Judgment:** Audience targeting and mandatory-vs-optional framing; how much manager enablement the Level 3 target requires.
- **Human reviews:** LMS configuration before any assignment blast (misconfiguration here is publicly visible and hard to walk back), and go/no-go after pilot.

### Step E1 — Evaluation

- **Inputs:** `EvaluationPlan` (authored back at Step A1 — this is the "plan backward from Level 4" discipline and should be a hard pipeline dependency, not a late addition), assessment data, survey data, business metrics, `PerformanceGapStatement`.
- **Outputs:** `Level1Report` (reaction, engagement, relevance), `Level2Report` + `ItemAnalysis` (difficulty, discrimination, distractor performance), `Level3Report` (behavior at 30/60/90 days), `Level4Report` (metric movement against the gap statement), `ROI_or_ROE_Calculation`, `EvaluationReport`, `RevisionBacklog`, `LifecycleDecision` (continue / revise / retire).
- **Judgment:** Attribution — isolating the training effect from concurrent changes; deciding when a weak result means bad course versus bad Level 3 conditions (no manager reinforcement, no opportunity to practice). Conflating these is the most common evaluation misread.
- **Human reviews:** the `Level4Report` attribution claims (a pipeline will overclaim causation), and the `LifecycleDecision` — retirement in particular needs an owner willing to remove things.
- **Feedback edges:** `ItemAnalysis` → Step D2 (bad items). `RevisionBacklog` → Step D4/D5. `Level3Report` → Step A1 (if behavior did not change, the gap was probably misdiagnosed as a knowledge problem — the loop closes at the top, not at the storyboard).

### Cross-cutting pipeline requirements

- **Provenance is mandatory.** Every instructional claim traces to a `SourceInventory` entry. This makes SME review verification rather than proofreading, and it is what makes automated content trustworthy enough to sign off.
- **Contradictions escalate; they never auto-resolve.**
- **The cut list is a first-class reviewable artifact.** What a pipeline excludes is the thing humans most need to see.
- **A human must be able to answer "no course."** Step A1's gate is the only defense against a system that is structurally biased toward producing its own output.
- **Real learners are irreplaceable.** Formative tryout between Alpha and Beta is the one input no agent supplies.

---

## Sources

- [Devlin Peck — What is the ADDIE Model of Instructional Design? 2025 Guide](https://www.devlinpeck.com/content/addie-instructional-design)
- [InstructionalDesign.org — ADDIE Model](https://www.instructionaldesign.org/models/addie/)
- [Research.com — The ADDIE Model Explained: Evolution, Steps, and Applications](https://research.com/education/the-addie-model)
- [D2L — What Is the ADDIE Model of Instructional Design](https://www.d2l.com/blog/what-is-the-addie-model-of-instructional-design/)
- [Instructional Design Central — ADDIE Model](https://www.instructionaldesigncentral.com/addie-model)
- [eLearning Industry — Alpha, Beta, Gold Stages In eLearning Content Development](https://elearningindustry.com/what-are-alpha-beta-gold-stages-in-elearning-content-development)
- [Thinkdom — Exploring Alpha, Beta, Gold Stages](https://www.thinkdom.co/post/exploring-alpha-beta-gold-stages-in-elearning-content-development)
- [Omniplex Learning — The ABCs of the eLearning content development stages](https://omniplexlearning.com/blog/the-abcs-of-the-elearning-content-development-stages/)
- [eFront — The stages of eLearning content development](https://www.efrontlearning.com/blog/2015/07/the-stages-of-elearning-content-development.html)
- [eLearning Industry — SAM: A Rapid Design And Development Model](https://elearningindustry.com/sam-successive-approximation-model-for-rapid-instructional-design)
- [AIHR — ADDIE vs SAM: Key Differences](https://www.aihr.com/blog/addie-vs-sam/)
- [ELM Learning — Iterative Design Models: ADDIE vs SAM](https://elmlearning.com/blog/iterative-design-models-addie-vs-sam/)
- [Articulate E-Learning Heroes — An Introduction to SAM for Instructional Designers](https://community.articulate.com/blog/articles/an-introduction-to-sam-for-instructional-designers/1124165)
- [Learning Guild — Reconciling ADDIE and Agile](https://www.learningguild.com/articles/reconciling-addie-and-agile)
- [Cognota — What is Agile Instructional Design Methodology?](https://cognota.com/blog/what-is-agile-instructional-design-methodology/)
- [CommLab India — Agile Instructional Design: Running Sprints](https://www.commlabindia.com/blog/agile-instructional-design-sprints)
- [The eLearning Coach — Your Guide to Doing a SME Interview for Course Development](https://theelearningcoach.com/elearning_design/subject-matter-experts/)
- [Foundations of Instructional Design — Task analysis (skills and knowledge analysis)](https://id.rjhogue.name/foundations/chapter/task-analysis-skills-and-knowledge-analysis/)
- [LibreTexts — Task and Content Analysis (Design for Learning, McDonald & West)](https://socialsci.libretexts.org/Bookshelves/Education_and_Professional_Development/Design_for_Learning_-_Principles_Processes_and_Praxis_(McDonald_and_West)/01:_Instructional_Design_Practice/02:_Exploring/2.02:_Task_And_Content_Analysis)
- [Devlin Peck — The Kirkpatrick Model: Four Levels of Training Evaluation](https://www.devlinpeck.com/content/kirkpatrick-model-evaluation)
- [Learning Guild — Buzzword Decoder: Kirkpatrick Levels of Evaluation](https://www.learningguild.com/articles/2529/buzzword-decoder-kirkpatrick-levels-of-evaluation/)
- [Valamis — Kirkpatrick model: how to evaluate whether training worked](https://www.valamis.com/hub/kirkpatrick-model)
- [eiDesign — How to Apply the Kirkpatrick Model of Training Evaluation in 2025](https://www.eidesign.net/measuring-elearning-roi-with-kirkpatricks-model-of-training-evaluation/)
