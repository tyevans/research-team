# Remove the workflow system

Executes BACKLOG B147. The workflow/preset system -- `hybrid.default`,
`ubd.pure`, `addie.pure`, their stages, stage artifacts, stage exits, the check
library, check telemetry, and the course/stage/artifact/finding surfaces --
comes out entirely. The curriculum -> catalog -> realization -> UbD authoring
path is the spine that remains.

Two surveys precede this and are not repeated here:
`docs/reports/workflow-system-removal-survey.md` (where it lives) and
`docs/reports/post-workflow-cohesion.md` (what the product should be
afterwards). Read both before starting a slice.

## What was measured, 2026-08-27, against `~/.research-team/sessions.db`

The plan turns on this and it was taken before any code was written.

| Fact | Value |
|---|---|
| `ProjectWorkflowSelected` events | **0** |
| `ProjectStageAdvanced` events | **0** |
| `StageChecksEvaluated` events | **0** |
| `check_outcomes` rows | **0** |
| `topics` rows | **64**, across 6 projects |
| `courses` / `authoring_runs` rows | 7 / 18 |

**The log holds nothing from this system.** B147 says "the log is the part to
think about first"; it is empty. Removing the event types cannot break a replay
of the real database because there are no rows of those types to replay. The
schema-evolution refusal case is therefore a statement of intent for a future
reader rather than a guard over data -- write it anyway, and say in its
docstring that it guards nothing today, because the next person will otherwise
assume it was load-bearing.

The same query settles the cohesion report's §2.3 open question in the other
direction: topics are alive on every real project, so QUEUE becoming the topic
queue is justified on data rather than on symmetry.

## Decisions taken

Owner's steer: breaking changes are free (pre-release, single user), and
endpoints that genuinely make sense are wanted rather than tolerated.

1. **Remove all five dead event shapes outright** -- `ProjectWorkflowSelected`,
   `ProjectStageAdvanced`, `StageChecksEvaluated`,
   `SessionPurpose.WORKFLOW_STAGE`, `ToolCallDecided.stage`. No tombstones. One
   rule for all five, so a later reader never has to work out which of two
   regimes applies to which event.
2. **`GET /api/projects/{project_id}` is added first**, as a real resource
   rather than as scaffolding for the removal. Today the only single-project
   read is `/course`, which is an accident.
3. **No human gate on an authoring run.** The stage gate's `ask` floor is
   discarded deliberately, not by omission -- see the commit message
   requirement in Slice 8.
4. **Curriculum tab promotion and splitting `course` out are not in this PR.**
   Backlog entries instead. The diff is large enough that an IA change inside
   it would be unreviewable.

## Slices

Sequential. Each slice ends green on the gates named in it, and each is one
commit. **One agent per slice, dispatched one at a time** -- these are not
independent, and a layer's deletion breaks the compile of the layer above it.

### Slice 0 -- `GET /api/projects/{project_id}` (prerequisite)

Nothing is deleted here. This is additive and must be green before Slice 1.

- Add the route to `interfaces/web/app.py`, answering
  `{id, name, active_session_id, tip_at_event}`.
- Add `project_detail_view` to `presenters.py` -- `project_view` minus
  `workflow` and `stage`.
- Frontend: `ProjectRepository.project(id)`, a DTO and mapper, and a new
  `useProject` hook in `presentation/project/` carrying `projectId`,
  `projectName`, `holdingSessionId`. Keep `useCourseRefresh`'s subscription to
  `project` frames whole and move it across -- that hook is what moves the
  holding-session link when somebody joins, and it is not workflow machinery.
- Repoint `ProjectView.tsx`'s `sessionId`, `has.hasSession` and
  `QueueHeader`'s `holdingSessionId`, and `App.tsx`'s `onLoaded` breadcrumb, at
  the new hook. Leave `useCourse` in place and still used for the course tabs.

Why first: `/course` carries `projectId`, `projectName` and
`holdingSessionId` alongside the workflow fields, and four live consumers read
them. Deleting the route before this exists takes the transcript, the composer,
the Workspace tab and the breadcrumb name with it, and the symptom is not a 404
-- those surfaces just stop being drawn.

Gates: `pytest tests/interfaces/`, `npm run verify`.

### Slice 1 -- the console

- Delete `domain/project/course.ts` + test; `presentation/course/`'s workflow
  half (`ArtifactList`, `Artifacts*`, `Findings*`, `StageList*`, `StageRail*`,
  `use-course.ts`, `CoursePanes.*`, `course-fixtures.ts`);
  `entity/project/WorkflowChip.tsx` + stories; `common/findings-copy.ts`.
- **Move the survivors** -- `ExtractionPane`, `RunPanel`, `Workers*`,
  `WorkerDrawer`, `AutonomyPanel`, `AutonomyAllowAll`, `autonomy-copy.ts`,
  `shelf-borders.browser.test.tsx` and their stories/tests -- into
  `presentation/project/queue/` beside `QueueHeader.tsx`, then delete
  `presentation/course/`. Every `../../course/` reach-up in `QueueHeader`
  becomes `./`.
- `ProjectView.tsx`: drop the `artifact`, `finding` and `stage` tabs and
  facets, and `hasCourse`. Keep `visibleMaterialTabs` with its one surviving
  condition and the deep-link exemption -- that rule is load-bearing and gets
  re-derived wrong when inlined.
- QUEUE becomes the topic queue: `regionOf`'s `stage` case dies, the pane's
  `meta` becomes a count of open topics, and the comment above `'topic'` is
  rewritten to say what QUEUE is now.
- `NewProjectForm.tsx`: delete the preset `<select>` and `NO_WORKFLOW_COST`
  entirely, including the paragraph -- a form that explains itself where there
  is no decision is chrome. Creation becomes one server call; the
  two-call failure split goes with it.
- `AutonomyAllowAll.tsx` loses `stageGatesStillAsking` and the second button.
- `ProjectList.tsx`, `ProjectCard.tsx`, `repositories.ts`, `dto.ts`,
  `mappers.ts`, `project-repository.ts`, `queries/keys.ts`: drop `presets()`,
  `chooseWorkflow()`, `course()`, `WorkflowPreset` and the workflow columns.

**Move, do not retype, `visibleMaterialTabs`'s dwell measurement** (Artifacts 13
entries / 85% bounce, Findings 17 / 88%, Workspace 14 / 100%) into the slice's
commit message. It is the measured argument for this whole PR and the code that
holds it is being deleted. Keep the Workspace third in the code.

Gates: `npm run verify`, plus `npm run test:browser` -- the directory move
touches `shelf-borders.browser.test.tsx` and the tracks tests measure the tab
strip.

### Slice 2 -- web routes and presenters

- Routes: `GET`/`POST /api/projects/{id}/workflow`, `GET /api/workflows`,
  `GET /api/projects/{id}/course`, `_workflow_of`, `WorkflowChoice`, and
  `AutonomyRelaxAll.include_stage_gates`. Drop `workflow`/`stage` from
  `GET /api/projects`.
- Presenters: `preset_label`, `preset_view`, `stage_view`, `artifact_slot_view`,
  `finding_view`, `stage_progress_view`, `course_view`, `provenance_view`, and
  the workflow keys in `project_view`.
- CLI: the `/checks` command in `repl.py` and `CheckStat` rendering in
  `formatters.py`.

Gates: `pytest tests/interfaces/`, ruff.

### Slice 3 -- application

Delete: `stage_runner.py`, `stage_exit.py`, `checks.py`, `coverage.py`,
`course.py`, `check_telemetry_read.py`, **`prompts.py` and the `prompts/` tree**
(confirmed: `prompts/` holds only `ubd/`, six files, and the authoring path
holds its prompts as Python constants).

Amputate:

- `artifacts.py` splits and the module dies. `parse_frontmatter` (with its
  fence constant) into `application/frontmatter.py`; `slugify` into
  `application/text.py`. **Move `parse_frontmatter`'s docstring whole** -- it
  carries the measured `builds_toward` colon fix and is the only record of it.
- `findings.py` keeps `blocking | advisory | human_gate` and drops `invariant`
  and `critic_gate`. `human_gate` survives on `topic_attention.py:200`'s own
  merits. Trim `Finding.cites`'s docstring of its check half.
- `autonomy.py`: drop `ADVANCE_STAGE_TOOL`, `STAGE_GATE_TOOLS`, their
  `GATED_TOOLS`/`TOOL_FLOORS` entries, and make **`relax_all` parameterless** --
  delete the `include_stage_gates` flag and the paragraphs defending it
  together, since the branch no longer branches.
- `workers.py`: drop `"stage"` from `WorkerKind`, the `StagesInFlight`
  protocol, the `stages` argument, `_stage_detail`, the roster's stage arm, and
  one of five `active_projects` sources. The ordering comment loses its stage
  clause only.
- `session_service.py`: the `RecordStageReview` call.

Gates: `pytest tests/application/`, ruff.

### Slice 4 -- infrastructure

Delete `agent/workflow_tools.py`, `agent/stage_middleware.py` (with
`managed_tools_for`, which has no surviving caller -- verified),
`persistence/project_workflow.py`, `persistence/check_telemetry.py` and
`persistence/check_telemetry_reader.py`.

Gates: `pytest tests/infrastructure/`, ruff.

### Slice 5 -- composition

~25 sites. `WORKFLOW_DRIVEN`, `_resolved_workflow`, the `stage_runner` field
and construction, `StageMiddleware`, `EndTurnOnStageAdvance`, the
`_gate_and_advance` / `review_stage` callback, the `advance_stage` subtraction.

Note the consequence rather than discovering it: `WORKFLOW_DRIVEN` contained
`CHAT`, so an ordinary console session got the stage denylist whenever its
project had a preset. With `_resolved_workflow` gone that branch returns nothing
for every purpose and **no session gets a denylist**. That is the fix the
comment at `:1976-1984` wanted, arrived at by subtraction -- state it in the
commit message; do not leave it to be found.

Gates: `pytest tests/integration/`, ruff.

### Slice 6 -- domain and the log

- Delete `domain/workflow.py` and `workflows/`.
- `domain/project.py`: `ProjectWorkflowSelected`, `ProjectStageAdvanced`,
  `SelectWorkflow`, `AdvanceStage`, `current_stage_of`, and the four
  `ProjectState` fields. **Add no "where this project stands" field** -- that is
  derivable from reads the console already makes, and a stored derivation beside
  its own inputs is the workflow's original mistake in a new vocabulary.
- `domain/commands.py`: `SessionPurpose.WORKFLOW_STAGE`, `RecordStageReview`.
  Keep the enum's docstring argument against `drives_workflow: bool` -- it was
  never about the workflow.
- `domain/session.py` / `events.py`: `StageChecksEvaluated`,
  `ToolCallDecided.stage`.
- `tests/infrastructure/test_schema_evolution.py`: assert the **refusal** for
  all five shapes, per CLAUDE.md and `SessionStarted.project_id`'s precedent.
  Say in each docstring that the real log holds zero rows of these types, so
  the case guards intent rather than data.

Gates: `pytest tests/domain/ tests/infrastructure/`, ruff.

### Slice 7 -- test sweep and the architecture rule

Delete the 18 wholesale test files the survey names. Amputate
`tests/test_architecture.py`'s rule naming `research_team/workflows/`,
`tests/application/test_components.py`'s seven `ArtifactType` imports,
`tests/domain/test_project.py`, `test_persistence.py`, `test_web.py`,
`test_presenters.py`, `test_repl.py`.

**One decision inside this slice.** `application/components.py:1254`'s
`COMPONENTS_FOR: Mapping[ArtifactType, ...]` is the last live consumer of
`ArtifactType`. Read its callers before choosing: if nothing on the authoring
path reads the mapping, delete it with the enum. If something does, the mapping
must be rekeyed off a vocabulary the new path owns. Do not move `ArtifactType`
into the new path to preserve the mapping -- that carries the dead system's
vocabulary forward for one table's sake.

Gates: all four.

### Slice 8 -- docs, backlog, and the commit message

Delete: `docs/design/workflow-engine.md`, `docs/design/stage-boundaries.md`,
`docs/design/turn-purpose-and-workflow-attachment.md`,
`docs/features-course-view.md`, `docs/direction.md.bak`.

Historical banner (date + B147), do not delete: `docs/direction.md` §4.
Leave `docs/research/course-design/synthesis-generic-workflow.md` entirely alone
-- it is instructional-design research and never claimed to describe the code.

Rewrite: `README.md` (the most visible scar -- it describes a preset picker
that will not be in the form), `docs/direction.md` §§1/3/7 and its "Packaging
the workflow engine or the check library" future-work item,
`docs/features-landing-page.md`, and grep `docs/features-research-view.md`,
`docs/features-session-view.md`, `docs/design/facets-and-use-cases.md`,
`docs/design/architecture.md` for `stage`/`artifact`/`finding` rows.

BACKLOG: close B147. File four new entries, each recording a finding rather than
proposing symmetry:

1. **The grid convergence.** Three unrelated traditions each invented a
   two-dimensional coverage grid, and the intrinsic/relational split was a real
   distinction. A matrix becomes worth having again if authoring ever produces
   more than one artifact type per area. The reasoning is the asset; the code
   was the liability.
2. **A denominator for the authoring checkpoints.** A checkpoint that never
   fires and one that always passes are different, and only a denominator tells
   them apart. The four checkpoints have this question and no answer.
3. **Can `prose-critic` review a sibling's text?** `self_review_separation` was
   the one harness invariant in the old check library worth carrying over, and
   it belongs as a test over the dispatch table rather than as a check with a
   severity.
4. **Curriculum's place in the tab strip** -- promote to first, and/or split
   `course` out, now that the strip has two slots of headroom.

The PR description carries three things that exist nowhere else once the code is
gone: the dwell measurement from Slice 1, the zero-row event measurement above,
and **the discarded argument for a human gate on authoring runs** -- that a run
can produce four phases of confident wrong content and the checkpoints only
catch structural absence. Discarded on purpose, in writing.

Also name the orphaned `check_outcomes` table left in
`~/.research-team/sessions.db`. It is empty, which is the whole argument, but
CLAUDE.md's Read models section says to say so rather than leave it found.

Gates: all four.

## Standing rules for every slice

- **Do not run the full suite** -- run the slice's own tests plus `ruff check .`
  and `ruff format --check .`. The controller runs the full suite between
  slices. Repo-wide ruff is a separate CI job and covers files you did not
  touch.
- Never two `vitest` processes at once.
- A comment that explains an absence by pointing at another absence is a loop,
  not a reason. Several such comments are being deleted here; do not write new
  ones in their place.
- If a docstring's argument survives its subject's deletion by half, rewrite the
  surviving half to one sentence rather than trimming clauses off five
  paragraphs.
