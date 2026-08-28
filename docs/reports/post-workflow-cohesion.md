# After the workflow system: what the product should be

Written 2026-08-27, against B147 and
`docs/reports/workflow-system-removal-survey.md`. The survey answers *where the
old system lives*. This answers the question after it: **once the concept is
gone, what shape leaves one coherent product rather than a thing with an
amputation scar.**

Everything below was checked by reading the files named. Where a claim is
reasoning rather than measurement it says so. Where a choice belongs to the
owner it is written as a decision with options, not as a recommendation with a
silent premise.

---

## 0. The finding that should change the removal plan

**There is no `GET /api/projects/{project_id}`.** Grepped the route table in
`interfaces/web/app.py`: eighty-odd project routes, and every one of them is a
*sub*-resource — sources, topics, graph, ontology, curriculum, catalog,
timeline, dispatch. The only single-project read in the product is
`GET /api/projects/{project_id}/course`.

That endpoint is doing two unrelated jobs, and only one of them is the
workflow's:

```
frontend/src/domain/project/course.ts:16-38
  projectId, projectName, holdingSessionId   <- project identity
  preset, position, stageCount, stages,
  findings, unimplementedChecks              <- workflow
```

The first three have four live consumers that survive the removal:

- `ProjectView.tsx:707` — `sessionId = watching ?? course.data?.holdingSessionId`,
  which is what mounts the Holding-session tab, the Workspace tab, the scrub
  bar and the composer.
- `ProjectView.tsx` `has.hasSession` — the Workspace tab's visibility.
- `QueueHeader`'s `holdingSessionId` prop.
- `App.tsx:285` `onLoaded={onCourse}` — the breadcrumb's project name.

So a removal that deletes the route as the survey sequences it (frontend first,
then routes) takes the holding session and the project name with it, and the
symptom is not a 404 — it is the transcript, the composer and the workspace
quietly disappearing from every project page, plus a nameless breadcrumb. The
survey's step 2 does not name this and the frontend amputation list does not
either.

**Recommendation, and it is a prerequisite rather than a follow-up: add
`GET /api/projects/{project_id}` before deleting anything.** It answers
`{id, name, active_session_id, tip_at_event}` — `presenters.project_view` minus
`workflow` and `stage`, which is the same row `/api/projects` already builds
per project. `useCourse` becomes `useProject`, keeping `useCourseRefresh`
whole: that hook's subscription to `project` frames is what moves the
holding-session link when somebody joins, and it is not workflow machinery
(`use-course.ts:40-76`; the docstring's stage-advance reasoning dies, the
`ProjectSessionJoined` reasoning does not).

This also closes a note `use-course.ts:88-96` already leaves open — "a
per-project key would need a per-project route, which is backend work and not
this slice's". It is this slice's now.

Cost: one route, one presenter, one DTO, one hook rename, before the deletion
starts. Reasoned, not measured — I did not run the console.

---

## 1. Naming

### 1.1 "Course" — let the new meaning take the word

Two unrelated things carry the name today. After the removal only one survives,
so **no rename is needed on the new side.** `domain/course.py`,
`application/course_catalog.py`, `course_realization.py`,
`interfaces/web/course_html.py`, `frontend/src/domain/knowledge/course.ts` and
`presentation/curriculum/Course*.tsx` all keep their names and become
unambiguous by subtraction. That is the cheapest possible resolution of the
collision and it is available for free.

The one thing to guard: `frontend/src/domain/project/course.ts` and
`frontend/src/domain/knowledge/course.ts` differ only by directory today. Once
the first is gone, `@domain/knowledge/course.ts` is the only `course.ts` and an
import of the wrong one stops being possible.

**Do not rename `application/course_catalog.py` to `catalog.py` in the same
commit** even though it will read as redundant. The removal is already ~17,000
lines; a rename of a surviving module inside it makes the diff unreadable for
the one reason `git log` here exists.

### 1.2 `presentation/course/` — the directory name is the whole problem

Measured by listing: 34 files, of which the survey correctly identifies about
half as workflow. What is left after the deletion is:

| File | What it actually is |
|---|---|
| `ExtractionPane.tsx` + test, `ExtractionView.stories.tsx` | live `remember` progress |
| `RunPanel.tsx` + test, `RunView.stories.tsx` | starting an autonomous research run |
| `Workers.tsx`, `WorkerList.tsx`, `WorkerDrawer.tsx` + tests + stories | the worker roster |
| `AutonomyPanel.tsx` + test, `AutonomyAllowAll.tsx`, `autonomy-copy.ts` | tool-approval policy |
| `shelf-borders.browser.test.tsx` | a layout measurement over the above |

Every one of those is mounted by `QueueHeader` (`project/queue/QueueHeader.tsx:1-9`)
and by nothing else. They are not "course" components; they are the project
queue's chrome, and they live under `course/` because the course page is where
they landed.

**Recommendation: move all of them into `presentation/project/queue/`, beside
`QueueHeader.tsx`, and delete `presentation/course/` entirely.** That directory
already exists with exactly one file in it, and every import in `QueueHeader`
is a `../../course/` reach-up that becomes a `./`. `SeedPanel` stays in
`research/` — it has its own mount reasoning recorded there and moving it is a
separate argument.

The alternative — keep the directory, rename it `run/` or `activity/` — is
worse: it invents a third noun for a set of components whose only shared
property is *which pane draws them*, which is what `queue/` already says.

### 1.3 `application/artifacts.py`

The module dies down to two functions with no relationship to each other:

- `slugify` — used by `topics.py`, `knowledge.py`.
- `parse_frontmatter` — used by `components.py`, `prompts.py`,
  `interfaces/web/app.py`.

Do **not** keep a module named `artifacts.py` holding them. Two options, and I
recommend the second:

1. One `application/markdown.py` holding both. Honest about `parse_frontmatter`,
   dishonest about `slugify`, which knows nothing about markdown.
2. `parse_frontmatter` (with `FRONTMATTER_FENCE`) into
   `application/frontmatter.py`; `slugify` into `application/text.py` or beside
   its heaviest consumer. Two small modules, each named for exactly what it
   does.

Note `parse_frontmatter`'s docstring carries a real, measured bug fix (the
`builds_toward` colon case). **Move the docstring with the function**, whole —
it is the only record of that measurement.

### 1.4 `application/findings.py`

Keep the module. `topic_attention.py` is a genuine second consumer and the
module's own docstring records why one shared `Finding` beats two.

`FindingSeverity` loses values, and the exact set is worth checking rather than
guessing. Grepped `topic_attention.py`: it registers `blocking` and `advisory`,
and `TriggerSpec.evaluate` **stamps `human_gate` directly** (`:200`) for a
trigger with no run. So after removal the live vocabulary is
`blocking | advisory | human_gate`, and only `invariant` and `critic_gate` are
dead.

That matters for §4 below: `human_gate` survives the removal on its own merits,
in the topic queue, which is the one place the gate idea already has a home
that does not depend on stages.

`Finding.cites`'s docstring should lose the "for a check the ids are the thing
at fault" half of its argument, since checks are the side that dies. The name
still earns itself.

### 1.5 `application/prompts.py`

Read it: this module is workflow-only, top to bottom. Every public function
takes a `Preset`, a `StageBase` or a `Generator` (`referenced_prompts`,
`unresolved`, `orphaned_refs`, `shared_ref_problems`,
`intended_for_disagreements`, `stage_prompt`, `prompting_for`), and its
`Prompt` frontmatter schema requires `methodology` and `intended_for` pointing
at `preset/stage` pairs. Its only production importer is `composition.py`.

**Recommendation: delete `application/prompts.py` and the `prompts/` tree with
it.** The survey lists it as "needs reading to see how much is stage-only"; the
answer is all of it.

Two things to check before cutting, both cheap:

- `test_no_prompt_file_is_orphaned` is named in `authoring_checkpoints.py:22-27`
  and refuses a file under `prompts/` that no prompt names. If the authoring
  path's prompts live under `prompts/`, that tree is not entirely
  workflow-owned. I did not resolve this; `prose_rubric.py`'s docstring says
  the rubric sits *beside its loader* rather than under `prompts/`, which
  suggests the tree is workflow's alone, but confirm by listing `prompts/`
  before deleting.
- `parse_frontmatter`'s only remaining Python callers after this are
  `components.py` and `app.py`.

What is genuinely lost: a file format for versioned, referenced, integrity-
checked prompt text. The new authoring path holds its prompts as Python string
constants interpolating `CHECKPOINT_MARKERS` — which is *better* for the
prompt/checkpoint contract (CLAUDE.md's rule, and the reason
`test_every_marker_a_checkpoint_searches_for_is_named_in_its_prompt` exists)
and worse for editability by a non-programmer. That trade is already made and
this removal does not re-open it.

### 1.6 `application/autonomy.py`

Small and mostly survives. What goes: `ADVANCE_STAGE_TOOL`, `STAGE_GATE_TOOLS`,
the `advance_stage` entry in `GATED_TOOLS` and in `TOOL_FLOORS`, and the
`include_stage_gates` parameter on `relax_all` (with the route flag and the
second button in `AutonomyAllowAll.tsx`).

**`relax_all` should become parameterless.** With `STAGE_GATE_TOOLS` empty the
flag is a parameter that cannot change the answer, and the docstring's long
argument for keeping the exclusion opt-in — five paragraphs of it — becomes
prose defending a branch that no longer branches. Delete the parameter and the
paragraphs together; leaving either is how a comment turns a defect into a
decision (CLAUDE.md, Events).

The `fetch` / `fetch_media` floors and their reasoning are untouched and are
the module's real content.

---

## 2. The console's information architecture

### 2.1 What the tab strip should be

`MATERIAL_TABS` is eleven entries and `MATERIAL_TABS`'s own comment records the
measurement that eleven is the ceiling: `project-tracks.browser.test.tsx`
measured MATERIAL's floor at 646px against 837px of tabs. Removing `artifact`
and `finding` takes it to nine and buys back roughly 150px of strip. That is
real headroom, and the temptation is to spend it. **Don't, yet** — see §2.4.

The strip afterwards, in the order it already has:

```
Holding session | Workspace | Documents | Media | Graph | Tree | Classes | Timeline | Curriculum
```

Two docstrings become wrong and must be rewritten rather than trimmed:

- `MATERIAL_TABS`'s "**Artifacts then Workspace, and the order is an argument
  rather than an accident**" paragraph argues an adjacency between two tabs, one
  of which is gone. The surviving half — Workspace is the live tree — needs one
  sentence, not five.
- `visibleMaterialTabs`'s whole opening measurement (Artifacts 13 entries / 85%
  bounce, Findings 17 / 88%, Workspace 14 / 100%) is a record of *why these
  panes were dead*, which is B147's own argument. It should not be deleted — it
  should move into the removal's **commit message**, which is where `git log`
  keeps reasoning here. What stays in the code is the Workspace third of it.

### 2.2 `hasCourse` gating: delete the concept, keep the mechanism

`visibleMaterialTabs` filters on two conditions. `hasCourse` dies with the
course query. `hasSession` does **not** — it is a different condition, the
docstring says so explicitly, and it stays true of plenty of projects.

So the function survives with one condition and one deep-link exemption. The
question is whether a one-condition filter earns a function.

**Recommendation: keep it.** The deep-link rule ("a tab the route explicitly
names is always offered") is load-bearing and non-obvious — dropping a tab
leaves Radix with a selected value no trigger carries — and it is the kind of
thing that gets re-derived wrong when inlined. It also keeps the seam where the
next conditional tab will go. Cost: a filter with one predicate reads as
over-built, and somebody will want to inline it in six months. That is the
cheaper of the two mistakes.

### 2.3 The QUEUE pane loses its spine — and this is the real hole

Today QUEUE is: `QueueHeader`, then `StageList`, then `TopicList`. Remove
`StageList` and QUEUE is a header band over a topic list. Also gone: the pane's
`meta` line (`"N of M stages left behind"`), which is the only thing the pane
header says about itself.

That is not a hole to fill with a replacement — it is a pane that becomes
honest. `TopicList` is a real queue over real data; the stage rail never was
(measured, B147: `workflow: null` on all three projects).

**Recommendation: QUEUE becomes the topic queue, named as such.** `Pane
id="queue" label="Queue"` should get `meta` from the topic queue instead — a
count of open topics, which `TopicList` already fetches. `regionOf`'s `stage`
case dies; `'topic'` stays as the first case and the comment above it ("a stage
and a topic are both work items — that they arrived from two different pages is
the accident") loses its subject and should be rewritten to say what QUEUE is
now: *the questions this project still owes an answer to.*

**Open question I could not settle by reading**: whether the topic queue is
itself alive on real data. B147 measured the course model dead; it says nothing
about topics. Before committing to "QUEUE is the topic queue", **measure
`GET /api/projects/{id}/topics` against the three real projects.** If topics are
also empty everywhere, QUEUE is a header band over nothing and the honest answer
is to fold `QueueHeader`'s controls into MATERIAL and drop the `Split` to one
region — a much larger change, and one that should be decided on data rather
than on this report.

### 2.4 Should `catalog`/`area`/`path`/`course` get their own tabs?

Four facets behind one Curriculum tab, chosen by a toggle inside the pane. The
recorded reason is that the strip stopped fitting at eleven. At nine it fits.

**This is a decision for the owner, not a recommendation.** Options:

- **(a) Leave it.** Zero work; the pane's internal toggle is already built and
  tested; the curriculum reads as one place. Cost: `course` — a whole authored
  course book — is reached only by going Curriculum → catalog → card, and it is
  the product's output.
- **(b) Split `course` out into its own tab.** The authored course is the thing
  the whole pipeline exists to produce and it currently has no top-level
  address in the console's chrome. Cost: one more tab against a strip with two
  slots of headroom, and a tab that is empty until something has been realized —
  exactly the failure `visibleMaterialTabs`'s measurement names, unless it is
  gated on "this project has at least one realized course".
- **(c) Promote Curriculum to first / default and demote Holding session.**
  `DEFAULT_MATERIAL` is already `catalog` on measured evidence (82 entries,
  20.6s median, 14% bounce — the lowest of any view). The docstring explicitly
  declines to demote `session` down the strip because "dwell measures what
  readers were handed, not what they would pick". After the removal the
  curriculum is unambiguously the spine, and first place is a claim about what
  the product is for rather than a dwell measurement.

I lean (c) then (b), in that order and as separate changes after the removal
lands. Neither belongs in the removal commit.

---

## 3. The project lifecycle

### 3.1 Creation

`NewProjectForm.tsx` is a name field, a workflow `<select>`, and a paragraph
that changes with the selection. Remove the select and it is a name field and a
button — which is *correct*, and the interesting question is what the paragraph
becomes.

Today it says what a project without a workflow gives up (`NO_WORKFLOW_COST`).
Afterwards there is nothing to give up. **Recommendation: delete the paragraph
rather than replace it with a "next steps" blurb.** A form that explains itself
where there is no decision to make is chrome. The next action belongs on the
project page, where the reader will be one second later, not in the form.

The second-order effect is worth naming: creation currently makes **two server
calls** (`projects.create` then `projects.chooseWorkflow`), with a comment
explaining that the second can fail alone. That whole failure mode and its
error-reporting split disappear. Creation becomes one call.

### 3.2 What the first meaningful decision becomes

The preset choice was the first decision a project made. Nothing replaces it at
creation, and it should not be replaced — **the first real decision moved
downstream and already exists: what corpus goes in.** A project with no
documents can do nothing, and the path is already built and reachable:
Documents tab → add sources → extract (`POST .../sources`,
`.../sources/extract`), then the graph, then the catalog.

**Recommendation: a fresh project should land on the Curriculum tab and be told
what to press.** `DEFAULT_MATERIAL` is already `catalog`, and `CatalogPane`'s
empty branch already renders a `role="status"` line naming how many candidates
are waiting (recorded in `DEFAULT_MATERIAL`'s docstring — "an empty catalog is
the one screen that tells a reader what to press"). What it does *not* do is
distinguish "no candidates because nothing is extracted" from "no candidates
because clustering found none", and only the first has an action.

That is the one genuinely new piece of work this removal creates, and it is
small: **an empty-catalog branch that reads the project's document count and
points at the Documents tab when it is zero.** Without it, a project created
after this change lands on a screen whose call to action is for a state it is
not in. Reasoned, not measured — I did not render it.

### 3.3 `ProjectState`

After amputation: `project_id`, `status`, `name`, `member_session_ids`,
`active_session_id`, `tip_session_id`, `tip_at_event`. Every one is about
identity, membership and the filesystem lineage. **No "where this project
stands" field remains, and none should be added.**

The argument is the one CLAUDE.md's Read models section already makes about
derivations: where a project stands is *derivable* — has it documents, has it
been extracted, does its graph cluster into areas, has any candidate been
realized — and every one of those already has a read. A `phase` field on
`ProjectState` would be a stored derivation beside its own inputs, and the
first time it disagreed with the reads nothing could adjudicate. It would also
be the workflow's mistake in a new vocabulary: a linear position asserted over
a process that is not linear (a project can be extracting more sources while a
course is being authored from what is already there).

If the console wants a "what should I do next" line, it belongs in the console,
computed from the reads it already makes.

---

## 4. What was good, and what is actually lost

Skeptical pass. For each idea: does the new path cover it, is it lost, is it
worth rebuilding.

### 4.1 The check library — **covered in the one form that ever worked**

`checks.py` is 2,031 lines and its opening docstring is the best design writing
in the repository. It is also the clearest instance of the thing CLAUDE.md
warns about: a library verified against fixtures and never against a run,
because there were no runs (`workflow: null`, everywhere).

`authoring_checkpoints.py` covers the part that survives contact with reality,
and it does so with the property `checks.py` argued for and could not get:
**every literal it greps for is a constant the prompt interpolates**, held by
`test_every_marker_a_checkpoint_searches_for_is_named_in_its_prompt` and
`test_the_marker_registry_covers_every_literal_constant`. That is a stronger
contract than `checks.py` ever had, over a path that actually runs.

What `checks.py` had that checkpoints do not:

- **Severity as a binding decision.** A check that is blocking in one stage and
  advisory in another. The checkpoints raise or pass — no gradation. Not worth
  rebuilding: there is one authoring pipeline, not three methodologies, so
  there is nothing to bind differently.
- **`self_review_separation` and `verdict_citation` as harness invariants.**
  Both defend against a model grading its own work, and the reasoning is sound
  and general. The authoring path has a `prose-critic` and a rubric
  (`prose_rubric.md`). **This is the one thing in the old library worth
  carrying over**, and as a question rather than as code: *can `prose-critic`
  end up reviewing text a sibling of itself wrote under the same prompt?* If
  yes, the invariant is real in the new vocabulary and should be a test over
  the dispatch table, not a check with a severity.

Everything else in the library — `coverage`, `recurrence`, `format_conformance`,
the seventeen parameterized queries — is a generalization over three
methodologies that will not exist. Rebuilding any of it would be symmetry.

### 4.2 The coverage matrix — **lost, and worth one backlog entry, not a rebuild**

`coverage.py`'s finding is genuinely interesting: three unrelated traditions
each invented a two-dimensional grid, and the intrinsic/relational split
(`AttributeAxis` vs `ArtifactAxis`) is a real distinction carefully drawn.

It is also entirely coupled to `ArtifactType` as an axis, so it dies with it,
and nothing in the new path has a grid. The nearest analogue — *does every
enduring understanding have a performance task* — already exists as
`check_stage_two`'s ratio, and it is a ratio because there are two axes with
one cell each. A matrix over one pair is a table.

**Recommendation: delete it, and file a backlog entry that records the finding
in prose** — that the grid convergence exists, and that a matrix becomes worth
having again if the authoring path ever produces more than one artifact type
per area. Do not port the module. The reasoning is the asset; the code is the
liability.

### 4.3 Human gates and critic gates — **half covered, half already elsewhere**

`human_gate` as a severity survives in `topic_attention.py:200`, which stamps it
for a trigger with no automated implementation. That is the idea intact, in a
subsystem that has data.

The *review-gate autonomy floor* (`TOOL_FLOORS[ADVANCE_STAGE_TOOL] = "ask"`) is
the interesting loss and deserves a straight answer. Its argument: a stage
boundary is where a person looks at what was produced before the run builds on
it, and the interrupt/announce/prompt/record path is that review, already built.

**Does the authoring path have an equivalent boundary?** It has four phases with
Python checkpoints between them, which is the *machine* half. What it does not
have is a place where a person is asked. `POST .../curriculum/author` fires and
runs to completion or refusal.

Two honest readings, and this is a decision for the owner:

- **(a) That is correct and the floor was a mistake.** The four checkpoints
  assert on content, which is what the stage gate never did — the gate asked a
  human to look at output that no rule could judge. Authoring is cheap enough
  to re-run and the artifact is prose a person reads *afterwards*. No gate.
- **(b) The floor was defending something real and now nothing does.** A run
  that authors a whole area unattended can produce four phases of confident
  wrong content, and the checkpoints only catch structural absence. A pause
  after Stage 1 (desired results) — the phase everything downstream is built
  on — is the highest-value single interrupt in the pipeline.

I lean (a) for now, on the grounds that the interrupt machinery exists and can
be re-pointed at any tool later, and (b) is speculative until somebody has been
burned by an authored area. But (b) is the argument the removal is discarding,
so it should be discarded on purpose and in writing rather than by omission.

`critic_gate` — a finding that needs a model call the check library is
deliberately not allowed to make — is exactly what `prose-critic` is. It is
covered, in a better shape: a subagent rather than a severity.

### 4.4 Findings surfacing — **lost, and no home is needed**

The Findings tab read a stage's evaluated checks. Nothing in the new path
produces a stream of findings for a reader to browse: an authoring checkpoint
either raises and the run stops, or passes silently. The stop is the surfacing.

`topic_attention`'s findings *are* surfaced, through the topic queue's ordering
by worst severity. That is the same idea with a better consumer — a list ordered
by what is wrong, rather than a tab listing what was wrong.

**Recommendation: no rebuild.** If the authoring run's refusal message ever
needs to be readable after the fact, that is a question about
`GET .../curriculum/author`'s response, not about a findings surface.

### 4.5 Check telemetry — **lost, and the loss is small but should be named**

`CheckTelemetryProjection` folded `StageChecksEvaluated` into per-check fire
rate and override rate, and `docs/direction.md` §4 ("Closing the loop on
checks — built") is a page of careful reasoning about why the event has to
carry every *bound* check including the ones that found nothing, so a rate has
a denominator.

That reasoning is correct and it is about a system that never ran. Delete the
projection, the two read models, the `/checks` REPL command and `CheckStat`.

**Name the orphaned tables in the commit message** — `~/.research-team/sessions.db`
keeps them, and per CLAUDE.md's Read models section the honest thing is to say
so rather than leave someone to find them.

The idea worth keeping in a backlog entry: *a checkpoint that never fires and a
checkpoint that always passes are different, and only a denominator tells them
apart.* The four authoring checkpoints have exactly this question and no answer
to it today.

---

## 5. Ports and seams

### 5.1 `StagesInFlight` and the `'stage'` WorkerKind

`WorkerKind = Literal["run", "turn", "extraction", "dispatch", "stage"]`. Drop
`"stage"`; delete the `StagesInFlight` protocol, the `stages` constructor
argument, the `_stage_detail` helper, and the `stage` arm of the roster's
ordering.

The ordering comment (`workers.py:268-275`) explains why a stage sits with the
run and the dispatch — it holds the project for a whole stage rather than a
turn. That distinction survives for `run` and `dispatch` and the comment should
lose only its stage clause.

**Watch `active_projects()`** (`workers.py:401`): it unions the stage runner's
active projects into the set. After removal that union has one fewer source.
Check what reads `active_projects` before assuming nothing depended on a stage
run marking a project busy — I did not trace it.

### 5.2 The `advance_stage` exemptions in `composition.py`

The survey calls this the sharpest edge and it is right, but the exemptions are
**not** load-bearing for surviving tools. Read them:

- `managed_tools_for(preset.stages) - {ADVANCE_STAGE_TOOL}` (`:2309`) — subtracts
  the gate tool from a union computed *from the preset's stages*. Both the
  minuend and the subtrahend die together.
- `EndTurnOnStageAdvance()` in `base` (`:2264`) — bound whenever a workflow runs,
  inert without one. Dies.
- `_gate_and_advance` / `review_stage` callback (`:2338-2408`) — only ever
  reached for `advance_stage`.

The one that needs care is `WORKFLOW_DRIVEN = {CHAT, WORKFLOW_STAGE}` (`:260`).
Note **`CHAT` is in it** — an ordinary console session gets the stage gate,
prompt and denylist when its project has a preset. The comment at `:1976-1984`
records the failure that shaped it: the stage tool denylist was withdrawing
`list_sources`, `read_source` and `graph_search` from research rounds whose
whole job is reading the corpus.

**When `_resolved_workflow` is deleted, that whole branch returns nothing for
every purpose, so no session gets a denylist.** That is the fix the comment
wanted, arrived at by subtraction. Verify by reading rather than assuming that
`managed_tools_for` has no other caller — if it does, a chat session's tool set
changes as a side effect of this removal and that should be a stated
consequence rather than a surprise.

### 5.3 `SessionPurpose`

`WORKFLOW_STAGE` dies. `CHAT`, `RESEARCH_ROUND`, `TOPIC_SEEDING` and the fifth
(dispatch) survive.

The enum's docstring argues at length against `drives_workflow: bool` and for
keeping the five distinct so "which sessions were research rounds" stays
answerable. That argument **survives intact** — it was never about the workflow,
it was about not collapsing three kinds of unattended run. Keep the enum, keep
the reasoning, delete the member and the one sentence naming
`WORKFLOW_DRIVEN`.

**Decision for the owner: what happens to sessions already on the log with
`purpose: "workflow_stage"`.** Per CLAUDE.md this is a deliberate pre-release
break either way:

- **Tombstone** — keep the member, mark it deprecated in its docstring, nothing
  reads it. Replay of the real database stays clean. Cheap; leaves a member of
  a live enum that means "a thing this build cannot do".
- **Remove** — a replay of the real database raises on those rows. Loud, honest,
  and per the memory note *no backwards compatibility needed* (pre-release,
  break data rather than migrate) this is the house style.

The survey raises the same choice for `ProjectWorkflowSelected` /
`ProjectStageAdvanced` / `StageChecksEvaluated`. **Answer it once, the same way,
for all four** — a log where two of the dead events raise and two replay
silently is the worst outcome, because the next reader cannot tell which rule
is in force. My recommendation is removal, with
`test_schema_evolution` asserting the refusal, matching
`SessionStarted.project_id`'s precedent.

### 5.4 `ToolCallDecided.stage`

Already nullable. It can simply stop being set — no schema change, no refusal
case. But a field that is permanently `None` on every future row is a field
that reads as "this data is missing" rather than "this concept is gone".

**Recommendation: remove the field, and say so in the removal's schema-evolution
case** alongside the four above. If it is kept, its docstring must say the
concept is retired and the value is `None` forever — otherwise it is exactly
the shape CLAUDE.md's Extraction section warns about, a field optional in the
schema and absent in practice, indistinguishable from one the writer declined
to fill.

---

## 6. Docs

Judged by grep and by reading `direction.md`'s workflow sections.

**Delete outright** — these describe mechanisms that will not exist, and there is
no honest rewrite because there is no surviving subject:

- `docs/design/workflow-engine.md`
- `docs/design/stage-boundaries.md` (cited by `composition.py:922` and `:3286`;
  those citations die with their code)
- `docs/design/turn-purpose-and-workflow-attachment.md`
- `docs/features-course-view.md` (955 lines about a page that no longer exists —
  the course/research merge already superseded it, and this finishes the job)

**Mark historical rather than delete** — these hold reasoning worth keeping and
would be dishonest presented as current:

- `docs/direction.md` §4 ("Closing the loop on checks — built"). It is the best
  record of the fire-rate/denominator argument (§4.5 above), and it is now the
  history of a decision, not a description of the product. A `> Historical:`
  banner naming the date and B147 is the minimum.
- `docs/research/course-design/synthesis-generic-workflow.md` (cited by
  `checks.py:3`). This is instructional-design research, not a system
  description — it never claimed to describe the code and does not become wrong.
  Leave it entirely alone.

**Minimum honest rewrite** — these describe a real product with workflow-shaped
holes:

- `README.md` — check every mention of presets, stages and the course view.
  This is the file people-using-the-project read (CLAUDE.md says so) and a
  README describing a preset picker that is not in the form is the single most
  visible scar.
- `docs/direction.md` outside §4 — §§1, 3, 7 and the "Packaging the workflow
  engine or the check library" item under future work. The last one is a whole
  proposed direction that is now void.
- `docs/features-landing-page.md` — the workflow `<select>` and the
  workflow/stage columns.
- `docs/features-research-view.md`, `docs/features-session-view.md` — grep for
  `stage` before assuming they are clean; both predate the page merge.

**Leave alone**: `docs/ui-foundations.md` (1,296 lines and, on inspection, about
tokens, layout primitives and the border/cascade rules — the workflow hits are
in example markup at worst), `docs/design/learning-areas-and-paths.md`,
`docs/design/interactive-components.md`, `docs/design/facets-and-use-cases.md`
(check its facet table for `artifact`/`finding` rows), `docs/design/architecture.md`
(check its layer diagram).

`docs/direction.md.bak` should be deleted whatever else happens.

---

## 7. Decisions for the owner

Collected, so none is buried:

1. **Tombstone or remove the four dead event shapes** (`ProjectWorkflowSelected`,
   `ProjectStageAdvanced`, `StageChecksEvaluated`, `SessionPurpose.WORKFLOW_STAGE`)
   plus `ToolCallDecided.stage`. Recommend: remove, all five, one rule.
   (§5.3, §5.4)
2. **Is an authoring run allowed to complete unattended?** The stage gate's
   `ask` floor was the only place a person stood between a machine and its own
   output. Recommend: yes, no gate, but decide it rather than inherit it.
   (§4.3)
3. **Does the Curriculum tab stay one tab?** Options (a) leave, (b) split
   `course` out, (c) promote Curriculum to first. Recommend (c) then (b), both
   after the removal lands. (§2.4)
4. **Measure the topic queue before committing to QUEUE's new shape.** If topics
   are as dead as courses were, the two-region split is the next thing to
   question. (§2.3)

## 8. What I would do first

In order, and the first item is not optional:

1. Add `GET /api/projects/{project_id}`; move `useCourse` → `useProject` onto
   it, keeping only `projectId`, `projectName`, `holdingSessionId`. **This is a
   prerequisite for the survey's step 1**, not a follow-up. (§0)
2. Then the survey's order, unchanged, with `presentation/course/` → 
   `presentation/project/queue/` folded into its step 1 and
   `application/prompts.py` added to step 3.
3. Then the empty-catalog branch that tells a fresh project to add documents.
   Small, and without it a project created after this change lands on a call to
   action for a state it is not in. (§3.2)
4. Then the docs, in one commit, with the historical banners rather than
   deletions where §6 says so.

The `direction.md` §4 text and the `visibleMaterialTabs` dwell measurement are
the two pieces of writing this removal would destroy that are worth more than
the code around them. Both belong in the commit message.
