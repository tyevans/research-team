# Course Deliverables: What Actually Ships

**Scope.** The output side of course production. What a finished course *is* as a set of files, by modality; the full artifact inventory with learner-facing / facilitator-facing separation; packaging and interop standards with a blunt assessment of which are worth targeting in 2026; export targets realistic for a markdown-filesystem pipeline; the methodology-stage → deliverable mapping across UbD, ADDIE, and Tyler; and a v1 recommendation.

**Claim marking.** Claims sourced from the web carry inline citations. Claims that are my own inference or synthesis from practice knowledge — not directly verified in this session — are marked **[unverified]**. Treat those as needing a second look before they harden into spec.

---

## 1. What a Finished Course Deliverable Actually Is, By Modality

There is no single answer, and this is the central complication for a pipeline. "A course" denotes five substantially different file sets depending on how it is delivered. A system that emits one shape and calls it done will be wrong for four out of five buyers.

### 1.1 Instructor-Led Training (ILT) and Virtual ILT (VILT)

The delivery vehicle is a human. The deliverable is therefore *a script and a support kit for that human*, plus a parallel set of materials for the learner.

**Core files:**

| File | Purpose | Conventional format |
|---|---|---|
| **Facilitator Guide** (a.k.a. Leader Guide, Trainer Guide) | The master document. Everything the instructor needs to run the session. | Word/DOCX, heavily templated. Print-oriented. |
| **Participant Workbook** (a.k.a. Participant Guide, Learner Guide) | Learner's copy — the same spine with the facilitator-only content removed and blanks/space added. | Word/DOCX → PDF, often printed |
| **Slide Deck** | Projected visual support | PPTX (Google Slides in some orgs) |
| **Agenda / Timing Sheet** | At-a-glance run of show | Often the front matter of the facilitator guide, sometimes standalone |
| **Activity kits** | Case studies, role-play cards, scenario data sets, prompt cards | PDF, sometimes physical |
| **Job aids** | Post-session reference | 1-2 page PDF, laminated card, wallet card |
| **Materials/logistics checklist** | Room setup, equipment, supplies, pre-work | Checklist in guide front matter |

**Facilitator guide conventional structure.** The practitioner and vendor literature converges on a stable outline: course overview; course organization; goals and outcomes; instructor responsibilities; participant requirements and pre-work (reading, activities, prerequisite courses); a comprehensive materials list of every item needed to lead the program; agenda; then module-by-module lesson plans ([Great Circle Learning](https://www.greatcirclelearning.com/blog/key-components-of-a-well-constructed-facilitator-guide), [WorkRamp](https://www.workramp.com/blog/creating-facilitator-guides-to-deliver-better-instructor-led-trainings)). ATD's template guidance adds structural furniture: title pages for the whole course *and* for each module, table of contents, index, and appendix with references and job aids ([ATD](https://assets.td.org/m/3732b356d4ebcaab/original/Creating-a-Participant-Facilitator-Guide-0.pdf)).

Timing guidelines are placed up front and repeated per section, explicitly so a facilitator can onboard to unfamiliar material and stay on schedule across repeat deliveries ([Great Circle Learning](https://www.greatcirclelearning.com/blog/key-components-of-a-well-constructed-facilitator-guide)).

**Per-module lesson-plan block** — the repeating unit inside the guide **[unverified as a fixed convention; this is the common shape across templates I have seen, not a published standard]**:

```
Module N: <title>
  Duration: 45 min
  Objectives: <enabling objectives covered>
  Materials: <slides 12-19, handout 3, flipchart>
  Room setup: <tables of 4>
  ---
  [0:00-0:05] Opening / hook          [SLIDE 12]  SAY: "..."
  [0:05-0:20] Content delivery        [SLIDE 13-16]
                                       ASK: "..." → expected answers: ...
  [0:20-0:35] Activity                [HANDOUT 3]
                                       SETUP: ... DEBRIEF: ...
  [0:35-0:45] Practice + feedback
  ---
  Transition to Module N+1: "..."
  Common questions & answers: ...
  Troubleshooting: if the group is quiet, ...
```

The bracketed conventions — `SAY:`, `ASK:`, `DO:`, `[SLIDE n]`, timing brackets, transition lines — are the load-bearing typography of a facilitator guide. This is highly regular and highly generable.

**The extraction relationship.** Facilitator guide and participant workbook are not independent documents. Authoring tools in this space (LeaderGuide Pro is the category incumbent) work by *extracting* the participant guide from the facilitator guide — the two share a spine, and the participant version omits answer keys, debrief guidance, talk track, and timing ([Great Circle Learning](https://www.greatcirclelearning.com/help-leaderguide-pro-templates-overview)).

**This is directly relevant to the pipeline.** It is the same structural problem as withholding quiz answers: one authored source, two audience projections, with visibility as a per-block property. Solve it once and it covers both cases. See §2.1.

**VILT deltas from ILT:** breakout room plans with group assignment logic, poll/quiz definitions with timing, chat prompts, producer/co-host runbook, platform-specific setup (Zoom/Teams/Webex), engagement checkpoint schedule (the rule of thumb is an interaction every 5-7 minutes **[unverified]**), and shorter session blocks with explicit breaks.

### 1.2 Self-Paced eLearning

The delivery vehicle is software. The deliverable is a *packaged web application* plus its source project.

**What ships:**
- **Published course package** — a zip containing `imsmanifest.xml` (for SCORM/CC) or `cmi5.xml` (for cmi5), plus HTML/JS/CSS/media. This is the actual artifact the LMS ingests.
- **Source project file** — `.story` (Storyline), Rise project, `.cptx` (Captivate). Proprietary, and the reason lock-in is real: the package is not editable, only the source is.
- **Media assets** — video (MP4), audio (MP3/WAV VO), images, captions (VTT/SRT), transcripts.
- **Assessment bank** — items, keys, feedback, scoring rules. Usually embedded in the package rather than shipped separately, which makes it hard to reuse.
- **LMS metadata** — title, description, duration, tags, prerequisites, completion rules, thumbnail.
- **Accessibility conformance report / VPAT** where procurement requires it.
- **Job aids and downloadable resources** attached as course resources.
- **Design source** — storyboard, design document, style guide — shipped to the client in agency engagements as part of the handover so they can maintain it.

The distinguishing property: an eLearning deliverable is *executable and stateful*. It tracks. That tracking contract is what §3 is about, and it is the single largest source of accidental complexity in this whole domain.

### 1.3 Blended

Not a third thing — an orchestration of the first two, plus the connective tissue that is usually the part nobody writes.

**What is additionally required:**
- **Blended learning journey map / pathway diagram** — the sequence across modalities with timing (pre-work eLearning → live workshop → job aid → 30-day coaching check-in → assessment).
- **Pre-work and post-work packets** with completion gates.
- **Transition/handoff specs** — what the live session assumes was completed asynchronously, and what happens when it wasn't (it usually wasn't).
- **Manager reinforcement guide** — the Level 3 lever.
- **Curriculum/learning path configuration** in the LMS, with prerequisite chaining.
- **Spaced reinforcement schedule** — nudges, boosters, microlearning drips.

**[unverified]** In my experience the most commonly missing blended artifact is the "what if pre-work wasn't done" contingency, which every facilitator improvises and none of them document.

### 1.4 Cohort-Based

A course as a *scheduled social event*. Materials are necessary but insufficient; the deliverable includes operations.

**What ships:**
- **Cohort calendar / schedule** — dated sessions, deadlines, office hours, with timezone handling.
- **Syllabus** — the learner-facing contract (see §2.2).
- **Session plans** per live meeting (facilitator-guide-like but lighter).
- **Assignment briefs** with due dates and submission mechanics.
- **Rubrics** for anything peer- or instructor-assessed (see §2.1 on visibility).
- **Peer review protocol and pairing logic.**
- **Discussion prompts / forum seed content** per week.
- **Community norms / code of conduct.**
- **Onboarding sequence** — welcome email, platform orientation, intros prompt.
- **Communication cadence plan** — kickoff, weekly nudges, at-risk outreach triggers, completion/graduation.
- **Capstone brief and evaluation rubric.**
- **Facilitator/TA runbook** — grading turnaround SLAs, escalation, common questions.

**[unverified]** Cohort courses live or die on the communication cadence rather than the content, and completion rate is the metric the buyer cares about. A pipeline that emits only content for this modality has emitted maybe 40% of the deliverable.

### 1.5 Documentation-Style / Async-Written

The modality closest to what a markdown pipeline natively produces, and — not coincidentally — the one with the least standardization and the fewest interop demands. Think: an internal engineering curriculum, a "learn X" handbook, an open-source course repo, a developer academy.

**What ships:**
- **Structured markdown tree** with a navigation/ordering manifest.
- **Rendered static site** with search, cross-references, code highlighting, anchors.
- **Per-page front matter** — objectives, prerequisites, estimated time, difficulty, tags.
- **Runnable examples** — code blocks, notebooks, sandbox repos, exercise scaffolds.
- **Exercises with separate solution pages** (again: the visibility problem).
- **Self-check quizzes**, often ungraded and inline.
- **Glossary**, **reference index**, **further reading**.
- **PDF/EPUB build** for offline and for the people who still want a book.
- **Changelog / versioning** — the property that distinguishes maintained curriculum from a snapshot.

This modality has a real and underrated advantage: **it is the only one where the source format and the delivery format are nearly the same thing.** Everywhere else, authoring is a compile step into a lossy proprietary target.

---

## 2. Artifact Inventory and the Learner/Facilitator Split

### 2.1 The visibility axis

The team lead is right that this is the same problem as quiz answers, and it is worth stating generally because it recurs at least six times:

| Artifact | Learner-facing form | Facilitator-facing form |
|---|---|---|
| Assessment | Questions only | Questions + answer key + distractor rationale + item statistics |
| Exercise / activity | Instructions, materials, time limit | + setup, expected outcomes, debrief questions, common wrong turns, timing flex |
| Case study | Scenario | + teaching notes, intended analysis, discussion path |
| Rubric | Usually shown (see below) | + calibration examples, borderline guidance, grading notes |
| Slide deck | Slides | Slides + speaker notes |
| Workbook | Content with blanks/space | Same content + talk track + answers filled in |
| Schedule | Dates, deadlines | + prep lead times, grading windows, at-risk triggers |
| Objectives | Sometimes shown, phrased as "you will be able to" | Always shown, phrased as measurable behaviors with criteria |

**Design consequence.** Do not model this as two documents. Model it as **one authored source with per-block audience visibility**, and render two projections. That is exactly how the ILT tooling category works (extract participant guide from facilitator guide), and it generalizes cleanly to markdown: a fenced block or front-matter-scoped region tagged `audience: facilitator`. A single `--audience=learner|facilitator` render flag then produces both sets from one tree.

**Rubrics are the interesting edge case.** Assessment doctrine says rubrics should be *given to learners in advance* — transparency about criteria is a design feature, not a leak. But rubrics typically have a facilitator-only layer (calibration anchors, borderline judgment guidance, score-norming examples). So rubrics are not learner-facing or facilitator-facing; they are *both, at different depths*. This confirms that the right primitive is per-block visibility rather than per-document classification. **[unverified as universal practice — advance-disclosure of rubrics is standard in higher ed and common in corporate, but not universal.]**

### 2.2 Full inventory with classification

**L** = learner-facing, **F** = facilitator/instructor-facing, **B** = both (typically with a facilitator-only layer), **A** = admin/stakeholder-facing.

| Artifact | Aud. | Notes |
|---|---|---|
| Syllabus / course overview | L | The learner-facing contract: description, outcomes, schedule, policies, grading, materials, contact, accessibility statement |
| Learning objectives (learner phrasing) | L | "By the end of this module you will be able to…" |
| Learning objectives (design phrasing) | F/A | ABCD-structured, Bloom-tagged, assessment-linked |
| Course map / curriculum map | F/A | Objective-to-module matrix; internal design artifact |
| Module outline | B | Learner sees scope + time; facilitator sees objective refs + dependencies |
| Lesson plan | F | Timed, with talk track |
| Slide deck | B | Speaker notes are the F layer |
| Participant workbook | L | Extracted from facilitator guide |
| Facilitator guide | F | The whole thing |
| Handouts | L | |
| Job aids | L | Survives the course; often the highest-value artifact shipped |
| Activity instructions | B | Setup/debrief is F |
| Case studies | B | Teaching notes are F |
| Discussion prompts | B | Expected directions + facilitation moves are F |
| Assessments (formative) | L | Often ungraded, immediate feedback |
| Assessments (summative) | L | |
| Answer keys | F | |
| Item metadata (difficulty, discrimination, distractor rationale) | F | Feeds item analysis |
| Rubrics | B | Criteria L; calibration anchors F |
| Learner-facing schedule / calendar | L | |
| Prep/production schedule | F/A | |
| Pre-work packet | L | |
| Glossary | L | |
| Reading list / resources | L | |
| Accessibility statement | L | Learner-facing commitment + how to request accommodation |
| Accessibility conformance report / VPAT | A | Procurement artifact, distinct from the above |
| Completion criteria / grading policy | L | |
| Certificate template | L | |
| Design document | F/A | Internal |
| Storyboard | F/A | Internal |
| Evaluation plan & instruments | F/A | Level 1 survey is briefly L at point of use |
| LMS metadata | A | |
| Facilitator prep guide / train-the-trainer | F | |
| Manager reinforcement guide | F (manager) | Third audience — worth noting the axis has more than two values |

**Note the third audience.** Manager guides, and in some settings sponsor/exec summaries, mean "audience" is an enum, not a boolean. **[unverified]** but I'd design for `audience: [learner|instructor|manager|admin]` from the start; retrofitting a boolean to an enum is annoying.

---

## 3. Packaging and Interop Standards

This section is where a pipeline can burn arbitrary amounts of effort for little return, so I'll be direct about each.

### 3.1 SCORM 1.2

**What it is.** A zip containing `imsmanifest.xml` plus web content, which talks to the LMS via a JavaScript API to report completion, score, and bookmarking. Released 2001. Frozen.

**Status 2026.** Still the most widely supported single target. Industry buyer guidance is that any LMS worth considering in 2026 supports both SCORM 1.2 and 2004, and that a vendor unable to confirm this is a red flag ([BrainCert](https://blog.braincert.com/scorm-compliant-lms-a-practical-2026-buyers-guide/), [LMSPedia](https://lmspedia.org/what-is-scorm/)). SCORM 1.2 is characterized as "still dominant in compliance-driven LMS environments."

**Verdict: legacy-but-required.** Its data model is impoverished (single score, `cmi.core.lesson_status`, one attempt, 4096-char suspend data), and this is genuinely limiting. But it is the lingua franca — if you emit exactly one packaged format, this is the one with the highest probability of importing successfully anywhere.

**Cost to emit.** Low-to-moderate for a *content-only* package: the manifest is a modest XML document, and if you are not tracking anything beyond "completed," you barely touch the runtime API. Cost rises sharply the moment you want real assessment scoring, resume, and multi-SCO sequencing. **[unverified]** — a "SCORM-wrapped static site that reports complete on last-page-viewed" is a small amount of work; a SCORM package with faithful per-question tracking is not.

### 3.2 SCORM 2004 (2nd/3rd/4th Edition)

**What it is.** Adds sequencing and navigation rules (SN), a richer data model, multiple objectives, and interaction-level tracking.

**Status 2026.** SCORM 2004 4th Edition is described as the most widely deployed e-learning standard in 2026 despite being frozen since 2009, with every major LMS still importing it ([LMSPedia](https://lmspedia.org/what-is-scorm/), [T-Square](https://tsquare.com.tr/scorm-2004-vs-xapi-cmi5-2026/)). ADL has confirmed there will be no further SCORM versions ([LMSPedia](https://lmspedia.org/what-is-scorm/)).

**Verdict: legacy-but-required, and lower priority than 1.2 for a v1.** The sequencing-and-navigation model is notoriously complex and inconsistently implemented across LMSs — which is precisely why many vendors still ship 1.2. **[unverified but widely held in the field]** SCORM 2004's SN spec is the part everyone skips.

**Cost.** Higher than 1.2 for meaningfully more capability that a markdown-derived course probably doesn't need.

### 3.3 xAPI (Experience API / Tin Can)

**What it is.** Not a packaging format. A *statement* format (actor-verb-object) and an HTTP API for writing learning records to a Learning Record Store (LRS). Tracks learning that happens anywhere — mobile, simulation, on the job, in a VR headset ([LMSPedia](https://lmspedia.org/scorm-vs-xapi-guide/)).

**Status 2026.** Actively used, actively developed, real ecosystem. Also frequently misunderstood: xAPI alone does not tell an LMS how to *launch* or *complete* a course, and does not define a package. Orgs that adopted "xAPI" expecting a SCORM replacement often discovered they had a data format and no course lifecycle.

**Verdict: genuinely useful, but not a packaging target.** Emitting xAPI statements is meaningful only if a consuming LRS exists. Most buyers don't have one.

**Cost.** Low to emit statements; high to be *useful*, because usefulness lives in vocabulary/profile design and downstream analytics, not in the wire format.

### 3.4 cmi5

**What it is.** The bridge: xAPI's data model plus SCORM-style launch, course structure (`cmi5.xml`), and completion/pass reporting. Developed under ADL — the same body behind SCORM — explicitly as SCORM's successor ([LMSPedia](https://lmspedia.org/cmi5-guide-for-lms-admins-developers/), [iCAN](https://icantech.ai/insights/xapi-vs-scorm-vs-cmi5-learning-standards-comparison)).

**Status 2026.** Adoption is real and growing fastest in US federal and military training, but has not displaced SCORM elsewhere ([LMSPedia](https://lmspedia.org/cmi5-guide-for-lms-admins-developers/)). Multiple 2026 vendor guides now recommend cmi5 as the default for *new* learning products, with SCORM 2004 reserved for legacy-LMS lock-in ([T-Square](https://tsquare.com.tr/scorm-2004-vs-xapi-cmi5-2026/)).

**Verdict: the correct long-term target, and the wrong v1 target.** Note that the sources recommending cmi5 as the 2026 default are LMS vendors and consultancies — parties with an interest in modernization narratives. The load-bearing fact underneath is less flattering: cmi5 has been "the successor" since 2016 and after a decade still has not displaced SCORM outside defense. Emitting cmi5 that no buyer's LMS ingests is worse than emitting nothing.

**Cost.** Moderate. `cmi5.xml` is simpler than SCORM's SN, but the runtime (fetch the auth token, send `initialized`/`completed`/`passed` statements to the LRS the LMS designates) is a real integration, not a file format.

### 3.5 QTI (Question & Test Interoperability, 1EdTech)

**What it is.** An XML standard for assessment items, tests, and item banks — portable questions with response processing and feedback.

**Status 2026.** QTI 3.0 exists and Common Cartridge 1.4 incorporates it, while native support for the much older QTI 1.2 assessments and question banks continues unchanged ([1EdTech](https://www.1edtech.org/standards/cc), [1EdTech QTI v3 Implementation Guide](https://www.imsglobal.org/spec/qti/v3p0/impl)). That "QTI 1.2 native support is unchanged" note is telling: the installed base is still on a version from 2002.

**Verdict: worth targeting only if assessment portability is a stated requirement.** QTI is genuinely the right way to move question banks between systems, and it is genuinely verbose and painful to author. The practical reality is that QTI 1.2 (not 3.0) is what most LMS importers actually accept.

**Cost.** Moderate-to-high, and the XML is unpleasant. **[unverified]** — for a v1 emitting simple MCQ/true-false/short-answer, a QTI 1.2 subset is tractable; full response processing is not worth it.

### 3.6 Common Cartridge (1EdTech)

**What it is.** A course-level package format: content pages, links, discussions, assessments (via QTI), and LTI links, bundled as `.imscc`. Where SCORM packages *a module*, Common Cartridge packages *a course structure*. CC 1.4 bundles LTI 1.3/LTI Advantage and QTI 3.0 ([1EdTech](https://www.1edtech.org/standards/cc)).

**Status 2026.** Actively maintained and certified by 1EdTech; the standard interchange path between academic LMSs. Canvas imports `.imscc` and Moodle exports it ([Springer Publishing/Moodle instructions](https://media.springerpub.com/media/downloads/common-cartridge-instructions-for-moodle.pdf)).

**Critical caveat, and it is well documented.** CC is explicitly a *lossy* interchange format. Moodle community guidance states plainly that "CC does not support all of the concepts in a Moodle course — CC has no concepts such as assignments or wiki pages, so these things have to fit into Common Cartridge as best they can," and that cross-LMS native imports are "the exception rather than the norm," with CC intended to offer "lower but still useful fidelity" ([Moodle.org](https://moodle.org/mod/forum/discuss.php?d=437120)).

**Verdict: the best LMS-import target for a content-shaped course, with expectations set low.** If your course is structured pages + links + simple quizzes — which is exactly what a markdown pipeline produces — CC is a good fit, because you are not producing the rich interactive constructs CC would lose. The lossiness that hurts an eLearning package barely scratches a documentation-style course.

**Cost.** Low-to-moderate. The manifest is a directory listing plus a resource-typed table of contents. **[unverified]** — a CC 1.1 export of HTML pages + web links is one of the cheapest real LMS-import wins available. Adding QTI-based quizzes raises the cost substantially.

### 3.7 LTI (Learning Tools Interoperability, 1EdTech)

**What it is.** Not a packaging format at all — a *launch and integration* protocol. LTI lets an external tool be embedded in an LMS course with SSO and grade passback. LTI 1.3 / LTI Advantage is current, using OIDC and JWT; 1EdTech is actively working on cookieless flow and grade passback ([1EdTech](https://www.1edtech.org/standards/roadmap)).

**Verdict: irrelevant to a v1, essential if you ever host.** LTI matters when *you run a service* the LMS launches into. It is meaningless for exported files. If this project ever becomes hosted rather than generative, LTI 1.3 becomes the integration story and it is a substantial one.

**Cost.** High. It's an OAuth/OIDC integration with a certification process.

### 3.8 Summary judgment

| Standard | Category | Target in v1? |
|---|---|---|
| SCORM 1.2 | Legacy-but-required; highest import success rate | Maybe — content-only wrapper only |
| SCORM 2004 | Legacy-but-required; low marginal value over 1.2 | No |
| xAPI | Live and useful, but not a package | No |
| cmi5 | Correct successor, chronically pre-adoption outside defense | No |
| QTI 1.2 | Ugly, old, and what importers actually accept | Only if assessment portability is required |
| QTI 3.0 | Current, thin installed base | No |
| Common Cartridge 1.1/1.4 | Best fit for page-shaped courses; openly lossy | **Yes, best candidate** |
| LTI 1.3 | Hosting integration, not export | No |

**Nothing here is genuinely dead**, which is itself the finding. The eLearning standards landscape does not deprecate; it accretes. SCORM 1.2 is 25 years old and still the safest bet. Plan for permanence, not migration.

---

## 4. Export Targets for a Markdown Pipeline

The useful distinction the team lead asked for: **mechanical transforms** (deterministic, no new information required) vs. **authoring decisions** (the target needs information the markdown does not contain, so something must decide).

### 4.1 Static site

| Tool | Fit | Transform type |
|---|---|---|
| **Quarto** | Strongest for course/teaching sites. Markdown + executable Python/R/Julia/Observable, one authoring model across website, PDF, slides (revealjs/pptx/beamer), and book ([DevOpsSchool](https://www.devopsschool.com/blog/quarto-vs-marp-the-complete-educators-guide-to-automated-slide-creation-using-markdown/), [Quarto vs MkDocs](https://gautamkhorana.com/static-site-generators/compare/quarto-vs-mkdocs/)). Explicitly noted as more common on education sites than MkDocs. | Mechanical, given front matter and a `_quarto.yml` |
| **MkDocs (Material)** | Fast, simple, renders in five minutes vs. Quarto's configuration overhead. **But: MkDocs Material entered maintenance mode in November 2025 — bug fixes and security patches only, no new features** ([Quarto vs MkDocs](https://gautamkhorana.com/static-site-generators/compare/quarto-vs-mkdocs/)). | Mechanical |
| **Docusaurus** | React-based, strong versioning and i18n, good for developer-facing curricula | Mechanical; MDX tempts you into non-portable content |
| **Jupyter Book** | Strong for notebook-heavy technical courses; overlaps Quarto and is losing mindshare to it **[unverified]** | Mechanical |

**Recommendation: Quarto**, because it is the only one of the four that treats website + PDF + slides + book as outputs of *one source*, which is the exact shape of the course-deliverable problem. The maintenance-mode signal on MkDocs Material is a real argument against the obvious alternative.

**Transform class: mechanical**, conditional on the markdown carrying navigation order and per-page front matter. Those are pipeline outputs, not user decisions.

### 4.2 PDF

- **pandoc → LaTeX → PDF** — mature, ubiquitous, and the failure modes (missing LaTeX packages, unicode, float placement) are well-trodden. Mechanical *given a template*; the template is an authoring decision made once.
- **Typst** — dramatically faster, far more legible template language than LaTeX, growing quickly. **[unverified]** — smaller ecosystem, and pandoc's Typst writer is newer and less battle-tested than its LaTeX path.
- **Quarto → PDF** — wraps the above and is the path of least resistance if Quarto is already the site generator.

**Transform class: mechanical for content, authoring decision for design.** Page size, typography, whether the participant workbook has answer-blank space, whether there's a per-module cover page — these are choices. Make them once as templates; do not make them per course.

### 4.3 Slides from markdown

| Tool | Notes | Export |
|---|---|---|
| **Marp** | Produces HTML ~50x smaller than reveal.js and ~8x smaller than ioslides, ~2.8ms/slide render ([DevOpsSchool](https://www.devopsschool.com/blog/quarto-vs-marp-the-complete-educators-guide-to-automated-slide-creation-using-markdown/)). Exports self-contained HTML, **PPTX**, PDF. Best for quick, printable decks. | HTML, PPTX, PDF |
| **reveal.js** | Most capable/customizable; the target for visually rich decks ([dasroot](https://dasroot.net/posts/2026/04/markdown-presentation-tools-marp-slidev-reveal-js/)) | HTML, PDF via print |
| **Quarto → revealjs** | Quarto supports revealjs, pptx, and beamer, with revealjs the most capable unless Office or LaTeX output is needed | HTML, PPTX, Beamer |
| **Slidev** | Vue-based, interactive, code-centric | HTML, PDF, PNG |

Published guidance lands on a combination that maps neatly to our case: **use Quarto as the main system, Marp for quick PPTX/PDF decks, and never make PowerPoint the master source** ([DevOpsSchool](https://www.devopsschool.com/blog/quarto-vs-marp-the-complete-educators-guide-to-automated-slide-creation-using-markdown/)).

**Marp's PPTX export deserves emphasis.** Corporate L&D runs on PowerPoint, and "we need the deck in PPTX so the facilitator can tweak it" is a near-universal requirement. A markdown→PPTX path that a human can then edit is the single highest-value slide export for corporate buyers **[unverified as universal, but this matches the ILT reality in §1.1]**.

**Transform class: NOT purely mechanical.** This is the sharpest instance of the mechanical/authoring boundary. Prose markdown does not contain slide breaks, and it does not contain the *reduction* from paragraph to bullet. Auto-slicing a document at `##` produces a deck of dense text slides — which is the single most-mocked artifact in corporate training. **Slide content must be authored as slide content**, ideally by generating a separate `slides.md` from the same source of truth rather than transforming the prose. Speaker notes (`::: notes` in reveal/Quarto, `<!-- -->` HTML comments in Marp) are the natural home for the facilitator-visibility layer.

### 4.4 Anki

`.apkg` is a SQLite database in a zip; the practical path is generating a CSV/TSV for Anki's import or using a library like `genanki` **[unverified — I have not confirmed genanki's current maintenance status in this session]**.

**Transform class: authoring decision, decisively.** Prose does not contain flashcards. Deciding *what is worth memorizing* is instructional judgment, and the quality gap between well-authored cards and mechanically extracted definition pairs is enormous. Extracting `**term** — definition` pairs is mechanical and produces bad cards. This should be a deliberate generation step against the objectives (specifically the Bloom-remember/understand-level enabling objectives), not a transform.

**[unverified]** Also worth noting: Anki matters a great deal for language, medical, and certification study, and almost not at all for corporate compliance or soft-skills training. It is an audience-specific target, not a general one.

### 4.5 LMS import

- **Canvas** — imports Common Cartridge (`.imscc`), Moodle `.mbz` (via a "Moodle 1.9/2.x" content type), QTI question banks, and SCORM ([UNO guide](https://www.uno.edu/media/34516/download), [Canvas Community](https://community.canvaslms.com/t5/Question-Forum/Failure-importing-from-Moodle-to-Canvas/td-p/241783)). Also has a REST API, which for programmatic course construction is often better than any file format. **[unverified for our purposes but worth investigating — API-driven Canvas course creation sidesteps the entire CC fidelity problem.]**
- **Moodle** — imports Common Cartridge and its own `.mbz`; exports CC. Community reports of cross-LMS CC round-trips failing are common and long-standing ([Moodle.org](https://moodle.org/mod/forum/discuss.php?d=260498)).

**Reality check on fidelity.** Documented guidance is that `.mbz` files are fragile (you cannot remove files and rezip and expect it to work), and that CC deliberately trades fidelity for portability ([Moodle.org](https://moodle.org/mod/forum/discuss.php?d=437120)). Expect pages and links to survive, quizzes to survive imperfectly, and anything structural to be reinterpreted.

**Transform class: mechanical for pages+links; authoring decision for assessments and structure.**

### 4.6 Google Slides / Docs

**[unverified — I did not research this in session.]** No first-class markdown import for Slides; the realistic paths are (a) markdown → PPTX (Marp/Quarto) → upload to Drive, which converts, or (b) the Slides/Docs API for programmatic construction. Path (a) is cheap and mostly works with degraded formatting. Path (b) is a real integration with OAuth. Docs has better markdown-paste support than Slides.

**Transform class:** (a) mechanical with fidelity loss; (b) authoring decision plus integration cost.

### 4.7 The classification, compressed

**Mechanical** (deterministic given structured markdown + front matter): static site, PDF via template, EPUB, Common Cartridge pages+links, plain HTML, learner/facilitator projections of the same source.

**Authoring decisions** (require information not in prose): slide content and pacing, flashcards, assessment items, activity design, timing allocations, media specs, anything requiring reduction or selection.

The pipeline's real job is to *make those authoring decisions explicitly and store them as first-class markdown artifacts*, so that everything downstream can then be mechanical. Do not try to transform prose into slides. Generate slides as a deliverable, then render them mechanically.

---

## 5. Methodology Stage → Deliverable Mapping

| Deliverable | **Tyler** (1949) | **ADDIE** | **UbD** (Wiggins & McTighe) |
|---|---|---|---|
| Needs/gap analysis | Implicit in "purposes" — sources: learner, society, subject | **Analysis** | Not a phase; assumed as context |
| Learner profile | Sources of objectives (learner studies) | **Analysis** | Implicit in Stage 1 |
| Task analysis | Not addressed | **Analysis** | Not addressed |
| Learning objectives / desired results | **Purposes** (Q1) — the defining Tyler contribution | **Analysis→Design** boundary | **Stage 1: Desired Results** — plus essential questions, enduring understandings, transfer goals |
| Assessment plan, rubrics, item bank | **Q4: How to evaluate** — *last* | **Design** (in modern backward-design-influenced practice) | **Stage 2: Evidence** — *second, before any instruction* |
| Course map / sequence | **Q3: Organization of experiences** | **Design** | **Stage 3: Learning Plan** |
| Instructional strategy per objective | **Q2: Selection of experiences** | **Design** | **Stage 3** (WHERETO framework) |
| Design document / blueprint | Not named | **Design** — `DesignDocument` | Not named; the UbD Template *is* the blueprint |
| Storyboard | Not named | **Design** — `Storyboard` | Not named |
| Slide deck, workbook, media, eLearning build | Not named | **Development** — Alpha/Beta/Gold | Not named (UbD is largely silent on production) |
| Facilitator guide | Not named | **Development** | Not named |
| Deployment, LMS config, launch comms | Not named | **Implementation** | Not named |
| Evaluation instruments & reports | **Q4** (as summative appraisal) | **Evaluation** (+ formative throughout) | Continuous; Stage 2 evidence *is* the evaluation |

### Where they genuinely disagree

**1. When assessment gets designed — the real disagreement.** Tyler's four questions place evaluation *fourth and last*: decide purposes, select experiences, organize experiences, then determine whether purposes were attained. UbD inverts this as its central move — Stage 2 (evidence of learning) precedes Stage 3 (the learning plan) — explicitly to prevent activity-oriented and coverage-oriented design. Classic ADDIE places assessment in Design but is agnostic about ordering *within* Design; modern ADDIE practice has largely absorbed UbD's backward-design discipline **[unverified as a majority position, though it is the guidance in most contemporary ID writing]**.

**For a pipeline this is not an academic distinction.** It determines whether `AssessmentBlueprint` is an input to or an output of content generation. UbD says input. I'd follow UbD: generating assessments after content produces items that test what was written rather than what was required — the single most common assessment failure.

**2. Granularity and scope.** Tyler is a *curriculum* framework — it operates at program/course scope and has nothing to say about screens, media, or production. ADDIE spans all the way down to individual screens and asset production. UbD sits in between at unit scope, with a specific template artifact. A pipeline modeling all three needs an explicit scope level per stage, or the three will produce artifacts that don't nest.

**3. What counts as a deliverable at all.** ADDIE is the only one of the three that treats *production* as in-scope. Tyler and UbD both stop at design. Everything in §1 — facilitator guides, packaged builds, LMS metadata — comes from ADDIE's Development and Implementation phases and has no counterpart in the other two. **If the system's value proposition is "real course materials," ADDIE is the only one of the three methodologies that actually reaches the deliverable.** The other two are upstream design disciplines that produce inputs to ADDIE's Development phase.

**4. Evaluation's meaning.** Tyler's Q4 is appraisal against stated purposes — closed loop, summative. ADDIE splits formative (throughout) and summative, and layers Kirkpatrick on top for organizational impact. UbD folds evaluation into Stage 2 as designed-in evidence, largely dissolving the separate phase. Three different objects wearing one word.

**5. UbD's unique artifacts have no ADDIE counterpart.** Essential questions, enduring understandings, and transfer goals are UbD-specific and genuinely useful — and they don't map onto ADDIE's objective hierarchy, which is behavioral and task-derived. **[unverified]** but I'd model them as an additional layer on the objective set rather than trying to force a mapping.

---

## 6. Recommendation for v1

**I largely agree with the team lead's framing — "a directory of markdown that renders well and exports cleanly" — but for a sharper reason than convenience, and with two amendments.**

### The argument

The case for markdown-first is not that standards are hard. It is that **every packaging standard in §3 is a lossy compile target for a source format that must exist anyway.** SCORM, cmi5, and Common Cartridge are all containers for content authored elsewhere. Nobody authors in SCORM. So the source-of-truth question is settled independent of the export question, and markdown is a defensible answer to it: diffable, reviewable, greppable, agent-writable, and the only format where the human review gates from the ADDIE report can be ordinary pull-request review.

The stronger point: **the pipeline's differentiating value is upstream of packaging.** Turning unstructured research into a coherent, objective-aligned, provenance-carrying course is the hard part. Emitting `imsmanifest.xml` is not hard; it is just tedious, and it is a commodity — a dozen tools do it. Spending v1 effort on standards compliance is spending it on the part of the problem that is already solved.

The honest counter-argument, which I'll state because it is real: **for corporate L&D buyers, "does it produce a SCORM package" is a procurement gate, not a feature request.** A tool that cannot put a course into their LMS is a tool that produces homework for someone else. If the target user is a corporate instructional designer rather than an engineer or educator writing a technical curriculum, markdown-only is a genuine adoption barrier.

I think that counter-argument loses for v1, for three reasons:

1. The lossiness runs the right direction for us. CC and SCORM lose *interactive richness*, which a markdown-derived course doesn't have. A pages-and-links course survives export nearly intact. So the export can be added later without redesigning the source — the compile target does not constrain the source format.
2. The documentation-style modality (§1.5) is the one where source and delivery are nearly the same artifact, and it is a real, underserved market (engineering onboarding, developer academies, internal curricula, open-source courses) that needs *zero* standards compliance.
3. Deferring is cheap and reversible; getting the source model wrong is not.

### What v1 should emit

**A structured markdown tree with:**

1. **Per-block audience visibility** — the `audience: learner|instructor|manager|admin` enum, rendered into projections. This is the single most important structural decision in the whole output design, because it is load-bearing for facilitator guides, workbooks, answer keys, speaker notes, rubrics, and activity debriefs simultaneously (§2.1). Retrofitting it is expensive; building it in is nearly free.
2. **Front matter carrying the design metadata** — objective refs, Bloom level, prerequisites, estimated time, module/lesson position, and **source provenance** (the citation chain from the ADDIE report). Provenance in front matter is what makes SME review verification rather than proofreading.
3. **Separate authored artifacts, not derived ones**, for anything requiring judgment: `slides.md` authored as slides (not sliced from prose), assessment items with keys and distractor rationale, activity specs with setup/debrief, facilitator timing blocks.
4. **A course manifest** — ordering, module structure, artifact inventory, modality. This is the thing every export target needs and the thing markdown files individually cannot carry.

**Render/export in v1:**
- Static site via **Quarto** (mechanical)
- PDF via Quarto/pandoc, in both learner and facilitator projections (mechanical, templated)
- Slides via **Quarto→revealjs** and **Marp→PPTX** — PPTX specifically, because corporate facilitators will edit it (§4.3)
- Plain markdown tree as a first-class deliverable in its own right

**Defer:**
- SCORM 1.2 (add when a real user asks; it is a content-only wrapper and a bounded piece of work)
- SCORM 2004, cmi5, xAPI, LTI, QTI 3.0
- Anki (audience-specific; needs authored cards, not extraction)
- Google Slides/Docs API integration

**The one deferred item I'd reconsider soonest: Common Cartridge 1.1 export.** For a page-shaped course it is close to a directory listing plus a typed manifest, it is the standard interchange path for Canvas and Moodle, and its documented lossiness costs us almost nothing given what we produce (§3.6). It is plausibly the cheapest real-LMS-import win available and worth a spike before it is written off as "standards work."

### The failure mode to design against

Emitting a beautiful markdown tree that no one can get into their LMS, *and* emitting a SCORM package with dense auto-sliced text slides, are the same failure in different clothes: shipping the mechanical transform and calling the authoring decision done. The pipeline's job is to make the authoring decisions explicitly, store them as artifacts, and let everything downstream be mechanical. Get that boundary right in v1 and every export target added later is additive rather than a rewrite.

---

## Sources

**Facilitator guides / ILT**
- [ATD — Creating a Participant/Facilitator Guide](https://assets.td.org/m/3732b356d4ebcaab/original/Creating-a-Participant-Facilitator-Guide-0.pdf)
- [Great Circle Learning — Key Components of a Well-Constructed Facilitator Guide](https://www.greatcirclelearning.com/blog/key-components-of-a-well-constructed-facilitator-guide)
- [Great Circle Learning — LeaderGuide Pro Templates Overview](https://www.greatcirclelearning.com/help-leaderguide-pro-templates-overview)
- [WorkRamp — How to Create a Facilitator's Guide](https://www.workramp.com/blog/creating-facilitator-guides-to-deliver-better-instructor-led-trainings)

**Standards**
- [LMSPedia — What is SCORM? Full 2026 Guide](https://lmspedia.org/what-is-scorm/)
- [LMSPedia — SCORM vs xAPI: Key Differences & LMS Guide (2026)](https://lmspedia.org/scorm-vs-xapi-guide/)
- [LMSPedia — cmi5 Guide for LMS Admins & Developers 2026](https://lmspedia.org/cmi5-guide-for-lms-admins-developers/)
- [BrainCert — SCORM-Compliant LMS: A Practical 2026 Buyer's Guide](https://blog.braincert.com/scorm-compliant-lms-a-practical-2026-buyers-guide/)
- [T-Square — SCORM 2004 vs xAPI (cmi5): Which Standard in 2026?](https://tsquare.com.tr/scorm-2004-vs-xapi-cmi5-2026/)
- [iCAN — xAPI vs SCORM vs cmi5](https://icantech.ai/insights/xapi-vs-scorm-vs-cmi5-learning-standards-comparison)
- [1EdTech — Common Cartridge](https://www.1edtech.org/standards/cc)
- [1EdTech — Common Cartridge 1.4 Implementation Guide](https://www.imsglobal.org/spec/cc/v1p4/impl)
- [1EdTech — QTI v3 Best Practices and Implementation Guide](https://www.imsglobal.org/spec/qti/v3p0/impl)
- [1EdTech — Product Roadmap](https://www.1edtech.org/standards/roadmap)
- [Edlink — What are the 9 Standards from 1EdTech Consortium?](https://ed.link/community/ims-global-standards/)

**LMS import fidelity**
- [Moodle.org — Common Cartridge from Canvas](https://moodle.org/mod/forum/discuss.php?d=437120)
- [Moodle.org — Canvas to Moodle: Restoring IMSCC Backup Fails](https://moodle.org/mod/forum/discuss.php?d=260498)
- [University of New Orleans — Manually Importing a Moodle Course File into Canvas](https://www.uno.edu/media/34516/download)
- [Springer Publishing — Common Cartridge Import Instructions for Moodle](https://media.springerpub.com/media/downloads/common-cartridge-instructions-for-moodle.pdf)
- [Canvas Community — Failure importing from Moodle to Canvas](https://community.canvaslms.com/t5/Question-Forum/Failure-importing-from-Moodle-to-Canvas/td-p/241783)

**Export tooling**
- [DevOpsSchool — Quarto vs Marp: The Complete Educator's Guide to Automated Slide Creation Using Markdown](https://www.devopsschool.com/blog/quarto-vs-marp-the-complete-educators-guide-to-automated-slide-creation-using-markdown/)
- [dasroot — Markdown-Based Presentation Tools: Marp, Slidev, and reveal.js](https://dasroot.net/posts/2026/04/markdown-presentation-tools-marp-slidev-reveal-js/)
- [Deckary — Markdown Slides: Best Tools, Export Paths, and When to Use Them](https://deckary.com/blog/markdown-slides)
- [Gautam Khorana — Quarto vs MkDocs (2026)](https://gautamkhorana.com/static-site-generators/compare/quarto-vs-mkdocs/)
- [WMTips — MkDocs vs. Quarto: 2026 Market Share & Usage Comparison](https://www.wmtips.com/technologies/compare/mkdocs-vs-quarto/)
- [Awesome Quarto](https://github.com/mcanouil/awesome-quarto)
