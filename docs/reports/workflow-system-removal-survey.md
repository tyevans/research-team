# Where the workflow system lives

A survey taken 2026-08-27 to support B147 (remove the workflow/preset system;
the curriculum -> catalog -> course path replaces it). This is a map, not a
plan. Line counts are of whole files, so they are an upper bound on what a
deletion removes.

## The finding that matters most

**The new course path does not touch the old one.** Traced by import, not by
name:

- `application/course_authoring.py` imports `authoring_checkpoints`,
  `authoring_dispatch`, `components`, `session_service`, `domain.learning_area`.
  Nothing from `domain/workflow.py` or `workflows/`. B147 predicted this and it
  holds.
- `application/course_catalog.py`, `course_realization.py`, `curriculum.py`,
  `learning_paths.py`, `area_projection.py` reach `domain.course_catalog`,
  `domain.learning_area`, `domain.course` -- a separate vocabulary end to end.
- **`interfaces/web/course_html.py` (1784 lines) is on the *new* side**, and
  B147 lists it on the old side. It imports `application.components`,
  `entity_definitions`, `graph_export`, `timeline_read`, and its only consumer
  is `interfaces/web/export.py`, which renders the *authored* course book.
  It is not part of the removal. Correcting that entry is worth doing before
  anyone works from it.

The word "course" names two unrelated things in this tree, and that is the
single largest hazard in the removal. `application/course.py` is the old one
(stage progress over a preset). `course_catalog.py` / `course_realization.py` /
`course_html.py` are the new one.

## Layer by layer

### Domain -- the vocabulary

| File | Lines | Disposition |
|---|---|---|
| `domain/workflow.py` | 662 | Delete. Presets, stages, `ArtifactType`, `Check`, `Decision`, the spine, `problems()`. |
| `workflows/__init__.py`, `ubd.py`, `addie.py`, `hybrid.py` | 2017 | Delete. Pure data, importing only `domain.workflow`. |
| `domain/project.py` | -- | Amputate, not delete. `ProjectWorkflowSelected`, `ProjectStageAdvanced`, `SelectWorkflow`, `AdvanceStage`, `current_stage_of`, and the `preset_id` / `preset_version` / `current_stage` / `stage_history` fields on `ProjectState`. `ProjectCreated`, `ProjectSessionJoined`, `ProjectTipAdvanced`, `ProjectDeleted` all survive. |
| `domain/commands.py` | -- | `SessionPurpose.WORKFLOW_STAGE`, `RecordStageReview`. |
| `domain/session.py`, `domain/events.py` | -- | `StageChecksEvaluated` and the `RecordStageReview` case that appends it. |

Two live consumers of `domain.workflow` are **not** workflow features and need a
new home for one symbol each:

- `application/components.py:1254` -- `COMPONENTS_FOR: Mapping[ArtifactType, ...]`,
  a mapping from artifact type to which interactive components suit it. Used by
  the component registry, which the new authoring path depends on. Either the
  mapping dies with the presets or `ArtifactType` moves.
- `application/coverage.py` uses `ArtifactType` as a matrix axis; but coverage
  is workflow-only otherwise (see below), so this resolves itself.

### Application

Delete outright:

| File | Lines |
|---|---|
| `application/stage_runner.py` | 868 |
| `application/stage_exit.py` | 560 |
| `application/checks.py` | 2031 |
| `application/coverage.py` | 493 |
| `application/course.py` | 348 |
| `application/check_telemetry_read.py` | -- |

`checks.py` is the big one and it is genuinely workflow-only: its two importers
are `stage_exit.py` and `check_telemetry_read.py`, both dying.

Amputate:

- **`application/artifacts.py` (214)** splits. `slugify` is used by
  `topics.py` and `knowledge.py`; `parse_frontmatter` by `components.py`,
  `prompts.py` and `interfaces/web/app.py`. Both survive. `COURSE_DIR`,
  `stage_number`, `artifact_path`, `stage_artifact_paths`,
  `stage_artifact_instructions` go. Move the two survivors somewhere without
  "artifact" in the name.
- **`application/findings.py`** -- `Finding` / `FindingSeverity`. Consumers are
  `checks.py`, `coverage.py`, `stage_exit.py`, `course.py` (all dying) and
  **`topic_attention.py`** (survives). Keep the module, drop the dead severities
  (`human_gate`, `critic_gate`, and probably `invariant`) if `topic_attention`
  does not use them.
- **`application/prompts.py` (622)** and `application/autonomy.py` (187) --
  `prompts.py` builds stage system prompts from a `Generator`; `autonomy.py`
  holds `ADVANCE_STAGE_TOOL` and the stage-gate floor alongside `FETCH_TOOL`,
  `SEARCH_TOOL` and `GATED_TOOLS`, which are used all over. Autonomy survives
  minus the stage gate; prompts.py needs reading to see how much is stage-only.
- `application/workers.py` -- the `'stage'` `WorkerKind` and the `StagesInFlight`
  port.
- `application/session_service.py:777` -- the `RecordStageReview` call.

### Infrastructure

| File | Lines | Disposition |
|---|---|---|
| `infrastructure/agent/workflow_tools.py` | 325 | Delete (`advance_stage`). |
| `infrastructure/agent/stage_middleware.py` | 180 | Delete. |
| `infrastructure/persistence/project_workflow.py` | 46 | Delete. |
| `infrastructure/persistence/check_telemetry.py` + `check_telemetry_reader.py` | -- | Delete. Projection over `StageChecksEvaluated`; nothing else writes that event. |

Note this takes a **projection and its read-model table** with it -- and the CLI
`/checks` command and `interfaces/cli/formatters.py`'s `CheckStat` rendering.

### Interfaces

- `interfaces/web/app.py`: `GET/POST /api/projects/{id}/workflow`,
  `GET /api/workflows`, `GET /api/projects/{id}/course`, the `_workflow_of`
  helper, `WorkflowChoice`, and `AutonomyRelaxAll.include_stage_gates`. The
  `workflow`/`stage` keys also ride on `GET /api/projects`.
- `interfaces/web/presenters.py`: `preset_label`, `preset_view`, `stage_view`,
  `artifact_slot_view`, `finding_view`, `stage_progress_view`, `course_view`,
  `provenance_view`, and the workflow keys in `project_view`.
- `interfaces/cli/repl.py` + `formatters.py`: the `/checks` command.

### Frontend

Delete (2385 lines across these plus the ones counted below):

- `domain/project/course.ts` and `course.test.ts` -- the old `Course` aggregate.
  Distinct from `domain/knowledge/course.ts`, which is the new one and stays.
- `presentation/course/`: `ArtifactList.tsx`, `Artifacts.tsx` + stories + test,
  `Findings.tsx` + stories + test, `StageList.tsx` + stories + test,
  `StageRail.tsx` + test, `use-course.ts`, `CoursePanes.test.tsx`,
  `CoursePanes.stories.tsx`, `course-fixtures.ts`.
- `presentation/entity/project/WorkflowChip.tsx` + stories.
- `presentation/common/findings-copy.ts`.

**The directory is mixed.** `ExtractionPane`, `RunPanel`, `Workers*`,
`WorkerDrawer`, `AutonomyPanel`, `AutonomyAllowAll` live in
`presentation/course/` and are not workflow. They need somewhere else to live,
or the directory keeps a misleading name.

Amputate: `application/ports/repositories.ts` (`presets()`,
`chooseWorkflow()`, `course()`, `WorkflowPreset`), `infrastructure/http/dto.ts`
+ `mappers.ts` + `project-repository.ts`, `application/queries/keys.ts`,
`presentation/tree/NewProjectForm.tsx` (the preset `<select>` -- the whole
"choose a workflow at creation" step), `presentation/tree/ProjectList.tsx`,
`presentation/entity/project/ProjectCard.tsx`, and `ProjectView.tsx` (the
`artifact`, `finding` and `stage` tabs and the `hasCourse` gating, ~10 sites).

`AutonomyAllowAll.tsx` / `autonomy-copy.ts` lose `stageGatesStillAsking` and the
second button, which exists only for stage gates.

### Tests

~8500 lines across 18 files delete wholesale: `tests/domain/test_workflow.py`,
`tests/application/{test_stage_runner,test_stage_exit,test_checks,test_coverage,test_artifacts,test_course,test_preset_gates,test_ubd_prompts,test_prompts}.py`,
`tests/infrastructure/{test_workflow_tools,test_stage_middleware,test_advance_ends_turn,test_check_telemetry}.py`,
`tests/integration/{test_workflow_attachment,test_workflow_stage,test_advance_stage_gate,test_stage_is_prompted,test_course_artifacts}.py`,
`tests/application/test_check_telemetry_read.py`.

Amputate: `tests/domain/test_project.py`, `tests/infrastructure/test_persistence.py`,
`tests/infrastructure/test_schema_evolution.py`, `tests/interfaces/test_web.py`,
`tests/interfaces/test_presenters.py`, `tests/interfaces/test_repl.py`,
`tests/test_architecture.py` (which names `research_team/workflows/` in a rule),
`tests/application/test_components.py` (7 `ArtifactType` imports).

## The event log

`SessionStarted` does **not** carry a preset -- checked; its fields are
`system_prompt`, `model_name`, `project_id`, `purpose`. B147 says the session
aggregate carries workflow identity; what it actually carries is
`SessionPurpose.WORKFLOW_STAGE` (a value of an enum, not a field) and
`StageChecksEvaluated` (a separate event type on the `Session` stream).

The events that die, and what they are stored in:

- `Project` stream: `ProjectWorkflowSelected`, `ProjectStageAdvanced`.
- `Session` stream: `StageChecksEvaluated`; plus every `SessionStarted` whose
  `purpose` is `workflow_stage`.
- `ToolCallDecided.stage` -- already nullable, so it can just stop being set.

Per CLAUDE.md's Events rule this is a deliberate pre-release break: say so in
each field's docstring, and change
`tests/infrastructure/test_schema_evolution.py` to assert the **refusal**
rather than deleting the case -- the treatment `SessionStarted.project_id`
already had.

Removing the event types entirely means a replay of the real database raises on
those rows. The alternative is keeping them registered as tombstones with no
projection -- which, per CLAUDE.md, replays silently as APPLIED. Deciding which
is a decision for whoever does the work; the tombstone route is cheaper and the
loud route is more honest.

Separately: dropping `CheckTelemetryProjection` leaves its read-model tables
orphaned in `~/.research-team/sessions.db`. That is cosmetic but should be
named in the commit.

## What the data says

B147's measurement stands and is the argument: all three real projects report
`workflow: null`, so `GET /api/projects/{id}/course` answers 409 for every one
of them. The Findings tab, the Artifacts tab and the Queue pane have been dead
on real data since they shipped.

## Rough size

| Side | Delete | Amputate |
|---|---|---|
| Python (`research_team/`) | ~5900 lines | ~15 files |
| Python (`tests/`) | ~8500 lines | ~8 files |
| Frontend | ~2400 lines | ~9 files |

Around 17,000 lines removed, against roughly 30 files needing edits.

## Suggested order

1. Frontend first -- delete the tabs, the chip and the preset `<select>` from
   `NewProjectForm`. Nothing server-side depends on the console, and this makes
   the feature unreachable before anything under it moves.
2. Web routes and presenters.
3. `application/` -- `course.py`, `stage_runner.py`, `stage_exit.py`,
   `checks.py`, `coverage.py`, `check_telemetry_read.py`, and the
   `artifacts.py` / `findings.py` splits.
4. `infrastructure/` -- tools, middleware, `project_workflow`, check telemetry.
5. `composition.py` -- ~25 sites, best done last when everything it wires is
   already gone.
6. `domain/` -- `workflow.py`, `workflows/`, the project events, the session
   command and event. Schema-evolution test in the same commit.
7. Withdraw B147 and correct the `course_html.py` line in it either way.

`composition.py` is the sharpest edge: `WORKFLOW_DRIVEN`, the `stage_runner`
field, `StageMiddleware`, `managed_tools_for`, the `advance_stage` subtraction
from the granted-tools union, and the `review_stage` gate callback all interact,
and several comments there explain *why* `advance_stage` is exempted from
something. Read those before cutting -- the exemptions may be load-bearing for
tools that survive.
