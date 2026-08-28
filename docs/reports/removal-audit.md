# Audit of the workflow-system removal

Read-only audit of `worktree-remove-workflow-system` at `a501489`, taken
2026-08-27 against a clean working tree. Seven of the nine slices have landed
(Slice 0, the deleted-project fix, and Slices 1-6). Slices 7 and 8 are not in
the log; Slice 7's work appears to have been absorbed into Slices 3, 5 and 6,
and Slice 8 has not started.

**What I measured**: `uv run ruff check .` and `uv run ruff format --check .`
(both clean, 414 files), `uv run pytest --co -q` (**3631 of 3640 collected**, 9
deselected), and `git show main:<path>` diffs of two moved docstrings. **What I
reasoned**: everything else -- I read code and commit messages and ran no test
suite. The frontend suites were not run at all; another agent holds the machine
and CLAUDE.md forbids two `vitest` processes.

The approach worked. The system is gone, the tree imports, the Python side is
clean of every deleted name (`GateReview`, `gate_reviewer`, `check_telemetry`,
`StageRunner`, `managed_tools_for`, `ArtifactType`, `COMPONENTS_FOR`,
`component_guidance`, `stage_exit`, `RecordStageReview`, `current_stage_of` --
grep returns one hit across `research_team/` and `tests/`, and it is a
docstring in `test_schema_evolution.py` naming `StageRunner` as deleted). What
is left is nine findings, and **every one of them is on the console side or in
prose**. Six of the seven code-level survivors are comments; the two that are
not are both in the console, which had exactly one slice and will get no
second.

## (a) Real defects now in the tree

### A1. `deep_agent.py` still names the workflow gate as live behaviour

`infrastructure/agent/deep_agent.py:334`, in the `tools` property's docstring:

> A `tools_provider` adds what the run's own state implies -- today, the
> workflow gate -- and that cannot be reported here

There is no workflow gate. `composition.py:2074` passes `tools_provider=turn_tools`,
and `turn_tools` (`composition.py:1995-2003`) returns `await granted_tools(session)`
and nothing else. A reader auditing what a turn is actually bound -- which is
the exact question this docstring exists to answer -- is told the wrong thing
about the one seam that decides it.

Two siblings are the same defect one degree softer:
`deep_agent.py:52` justifies `MiddlewareProvider` being resolved per turn
because "a workflow stage can change between two of them", and `:61` justifies
`ToolProvider` because "selecting a workflow is an HTTP call that writes an
event and returns". Both arguments survive on other grounds (a grant is
attached mid-session and does the same thing); both currently rest on a
mechanism that does not exist. Slice 5's message claims it rewrote
`deep_agent.py`'s two citations of `StageMiddleware`; these three are a
different set and were missed.

**Fix**: `:334` says the fetch tools a grant unlocks; `:52` and `:61` argue
from the grant rather than from the preset.

### A2. The project SSE frame's `decision` has neither a producer nor a consumer

Slice 6 removed `decision` from the server frame and said so plainly
(`interfaces/web/presenters.py:527-532`: "the key could only ever have been
null -- which is a silent default rather than a field"). The console kept its
whole half:

- `infrastructure/http/dto.ts:316` -- `decision: maybe(z.string()).optional()`
- `infrastructure/sse/event-stream.ts:198` -- `decision: frame.data.decision ?? null`
- `application/ports/event-stream.ts:140` -- `readonly decision: string | null`
- `application/ports/event-stream.ts:110-131` -- the frame's docstring still
  describes "a stage advanced, a workflow was chosen" and explains `decision`
  as "the reviewer's verdict"
- `infrastructure/sse/event-stream.test.ts:205-234` -- two tests that decode
  `change: 'ProjectStageAdvanced'` with `decision: 'approve_with_edits'` and
  `change: 'ProjectWorkflowSelected'`, event names the server can no longer
  emit

Nothing reads it. The only consumer of a project frame in the tree is
`presentation/project/use-project.ts:62`, which matches on `kind` and
`projectId` and never touches `decision`. So this is a port field with both
ends gone, kept alive by two tests over payloads no server will send -- the
shape CLAUDE.md's "silent default" and "port with one adapter" entries describe.
Slice 1 was the only frontend slice, so nothing remaining in the plan removes it.

**Fix**: drop `decision` from the DTO, the port type and the decoder, and
repoint the two decoder tests onto surviving project events
(`ProjectSessionJoined`, `ProjectTipAdvanced`) -- the thing they actually prove
is that one frame kind carries every project event, and that is still true.

### A3. `'stage'` is still a worker kind in the console, and its dot has no dress

`infrastructure/http/mappers.ts:342-354` lists `'stage'` explicitly among the
kinds `toRoster` recognises, on the argument that falling back to `turn` is a
confident wrong answer. The server's `WorkerKind` is
`Literal["run", "turn", "extraction", "dispatch"]` (`application/workers.py:27`)
-- Slice 3 dropped `"stage"` along with `StagesInFlight` and `_stage_detail` --
so the branch is unreachable. `mappers.test.ts:242-265` asserts it, with a
fixture reading `ubd.pure · ubd.stage2.evidence`: a test over a shape no
producer can make, which is why it passes and proves nothing.

The second half is worse than the branch: Slice 1 deleted `.worker-dot-stage`
from `course.css`, so if a `stage` worker ever did arrive, `WorkerList.tsx:110`
would write `worker-dot worker-dot-stage` and get the base dot with no fill.
The mapper's care and the stylesheet's deletion now disagree.

**Fix**: drop `'stage'` from the narrowing and delete the test, or repoint it
onto `dispatch`, which is the kind the trap it guards was actually found on.

*Pre-existing and out of this removal's scope, but found on the way*:
`.worker-dot-dispatch` has never existed. `git show main:frontend/src/styles/course.css`
has `run`, `turn`, `extraction` and `stage` only, so a dispatch worker renders
an undressed dot today and did before this branch. Worth a backlog line, not a
fix here.

## (b) Deferred items nobody owns

### B1. Two live modules justify a file's location by a test that no longer exists

`application/prose_rubric.py:8-16` explains why `prose_rubric.md` sits beside
its loader:

> It sits here ... rather than under `prompts/`, because `prompts/` is loaded
> wholesale by `load_prompts` and every file in it must be named by some
> workflow preset -- `test_no_prompt_file_is_orphaned` in
> `tests/application/test_ubd_prompts.py` fails otherwise.

Slice 3 deleted `prompts.py` and the `prompts/` tree whole. Grepped: no
`load_prompts`, no `test_ubd_prompts.py`, no `test_no_prompt_file_is_orphaned`
anywhere in the tree. The paragraph's premise, its named check and its named
test file are all gone, and it ends by arguing that "a real orphan ... still
fails it" -- a claim about a check that cannot run.
`application/authoring_checkpoints.py:19-23` cites the same test for the same
placement.

This is exactly the class Slice 3 swept in `topic_dispatch.py` and
`ask_components.py` (`COMPONENTS_FOR`, `COURSE_DIR`) and missed twice.

**Fix**: one clause each -- the rubric lives beside its loader because it is
quoted into two subagents' prompts and is never resolved as a prompt file.

### B2. `course_authoring.py` opens by citing a deleted module in the present tense

`application/course_authoring.py:3-7`: "`workflows/ubd.py` encodes UbD's
three-stage shape and **terminates at a unit plan** ... The preset is
untouched; nothing below reads it." `research_team/workflows/` was deleted in
Slice 6. The argument -- that going past Stage 3 into materials is a declared
departure rather than a smuggled one -- outlives the file, but it is now
sourced to something no reader can open, and "the preset is untouched" reads as
a statement about a live artifact.

**Fix**: attribute the three-stage shape and the quote to UbD itself.

### B3. `topic_dispatch.py` compares a position to a deleted function

`application/topic_dispatch.py:121`: "`position` is the topic's index ... which
is the same thing `stage_number` is to a preset". `stage_number` died with
`artifacts.py` in Slice 3 -- the same commit that rewrote two *other* citations
in this same file. The sentence is complete without the comparison.

### B4. Slice 8 has not landed

Stated so it is not mistaken for done: `docs/design/workflow-engine.md`,
`docs/design/stage-boundaries.md`,
`docs/design/turn-purpose-and-workflow-attachment.md` and
`docs/features-course-view.md` are all still present;
`BACKLOG.md` holds one mention of B147 and none of the four new entries the
plan specifies. `docs/direction.md.bak` is already absent. Presumably in flight.

### B5. The two documents the plan makes mandatory are untracked, and are absent from this worktree

The plan's second paragraph says of `docs/reports/workflow-system-removal-survey.md`
and `docs/reports/post-workflow-cohesion.md`: "Read both before starting a
slice." Neither file exists in this worktree, and
`git log --all -- <both paths>` returns nothing -- they were never committed.
They exist only as untracked files in the main checkout at
`/home/ty/workspace/research-team/docs/reports/`. Every slice ran here, where
they are not.

I read them from the main checkout for this audit and they are substantial: the
cohesion report's §0 is where `GET /api/projects/{id}` as a prerequisite comes
from, and §5.2 is where "no session gets a denylist" was first reasoned out.
That reasoning currently survives on one machine's untracked disk.

**Fix**: commit both. I cannot tell whether the slice agents read them (they
could have, from the main checkout); what I can tell is that nothing in the
branch guarantees the next reader can.

One recommendation in them was flagged as untraced and is now answered:
cohesion §5.1 says "Watch `active_projects()` ... Check what reads it before
assuming nothing depended on a stage run marking a project busy -- I did not
trace it." Traced: `WorkerRoster.everywhere` (`workers.py:345-352`) is the only
reader, it unions four remaining sources, and the roster is the only thing that
consumes the result. Nothing external depended on it. Not a gap.

## (c) Cosmetic

- **C1.** `frontend/src/presentation/course/` exists on disk and is empty. Git
  does not track empty directories, so it will not reach a clone -- but it is
  in this worktree and greps into it look like the directory survived. `rmdir`.
- **C2.** `frontend/src/app/App.test.tsx:84-85` passes `workflow: null` and
  `stage: null` in the `projects.list` stub. `projectDetailDto` has neither
  key, and the container ends in `as unknown as AppContainer`, so this
  typechecks and asserts nothing. Drop the two lines.
- **C3.** `frontend/src/styles/course.css` still carries the name while dressing
  only queue-header components. Its own header says the rename is a separate
  diff and gives the reason (the three surviving families are written from
  template literals and are invisible to a class-name grep). Agreed; not a
  defect, and do not rename it in a comment sweep.

## The load-bearing claims, checked against code

| Claim | Verdict | Evidence |
|---|---|---|
| Every session sees every registered tool; no denylist anywhere | **Verified** (read) | `composition.py:2073-2074` wires the two providers. `turn_middleware` (`:2005-2034`) returns `ComponentFeedback` plus optionally `SearchAttemptsMiddleware`; neither filters a tool set. `turn_tools` (`:1995-2003`) returns `granted_tools(session)` alone. Grep for `denylist`/`denied` in `composition.py`: nothing. |
| Nothing reserves any tool from allow-all | **Verified** (read) | `autonomy.py:110` -- `relax_all(self)`, no parameter, loops `for tool in GATED_TOOLS` with no exemption. `GATED_TOOLS` (`:31-52`) is hazards only; `TOOL_FLOORS` (`:53-56`) holds `fetch` and `fetch_media`. |
| `GET /api/projects/{id}` covers everything `/course` supplied | **Verified** (diffed) | `git show main:.../presenters.py` -- `course_view` returned exactly two non-workflow keys, `project_name` and `holding_session_id`. `project_detail_view` (`presenters.py:312-339`) answers `name` and `active_session_id`. The remaining seven keys were preset, position, stages, findings and unimplemented checks. |
| A deleted project 404s on every project-scoped route | **Verified by reading, not executed** | `app.py:1181-1194` -- `_require_project` refuses `deleted` as well as `new`, and its docstring carries the reversal. The test is parametrised over five routes including `DELETE` and `/join`, and the commit records proving it red. I did not run it. |
| The five schema-evolution cases refuse, for the stated reasons | **Verified by reading, not executed** | `tests/infrastructure/test_schema_evolution.py:607-836`. Three `EventTypeNotFoundError` (registry keyed by class name; `StageChecksEvaluated` separate because it is on the session stream), one `ValidationError` on `purpose` (event type still registered, enum member gone), one `ValidationError` from `DomainEvent`'s own `extra="forbid"` on `review_id`. The mechanisms are as the commit describes. `REMOVING_THE_WORKFLOW_SYSTEM` carries the zero-row measurement and each docstring points at it. |
| `parse_frontmatter`'s measured `builds_toward` docstring survived the move | **Verified** (diffed) | `application/frontmatter.py:23-52` against `main:.../artifacts.py:114-158`. Function body byte-identical; docstring identical apart from the single clause the commit declares ("All three are things a check reports on" became "None of the three is a reason to raise here"). The colon/`yaml.safe_load`/setext-heading measurement is intact. |

## What Slices 3 and 4 could not verify, and what covered it

Both slices landed with the tree not importing -- `composition.py` imported
thirteen deleted modules and `tests/conftest.py` imports `composition`, so
pytest collected **zero tests repo-wide for two commits** and a `-q` tail would
have read as clean. Slice 3 substituted a probe (deleted modules restored from
`HEAD`, shims for four constants: 943 passed) and stated exactly what a probe
that restores the deletions cannot prove. That is the honest framing.

Slice 5 cleared it and ran `pytest tests/ --ignore=tests/integration` (3527
passed, 1 failed -- an architecture test deleted in that same commit) plus
integration (182 passed). Measured independently just now: ruff clean over 414
files and **3631 of 3640 tests collected**. So the Python half of Slices 3 and
4 is covered by runs at Slice 5 and later, and the "0 collected" window is
closed.

**The frontend is the half that is not covered.** Slice 1 ran `npm run verify`
and `npm run test:browser` and was the only slice to do so; Slices 2 through 6
then changed the server contract underneath it (the `decision` key, the worker
kind vocabulary, the project frame's event names). Findings A2 and A3 are both
in that window and both are the reason it matters: a suite that asserts on
payloads the server has stopped sending stays green. Nothing here is red -- but
nothing here has been asked.

## What I could not check

- Neither test suite was run. Collection only, plus both ruff gates.
- The frontend was not built, not typechecked and not rendered. Findings A2, A3
  and C2 are read from source; I did not confirm they compile after a fix,
  because I made none.
- No route was exercised against a real or copied database. The deleted-project
  404 and the five refusals are read, not run.
- Whether the slice agents actually read the two untracked reports. They are
  not in this worktree; they may have been read from the main checkout.
- The orphaned `check_outcomes` table in `~/.research-team/sessions.db`. I did
  not open the database; I am taking Slice 4's measurement (0 rows) as given,
  and the schema side is confirmed -- `read_models.py` declares no
  check-telemetry table, so a fresh database will not create one.
