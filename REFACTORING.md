# Refactoring & Codebase Health Playbook

A guide for autonomous agents and engineers working on large-scale refactoring, complexity reduction, and architectural unification in this repository.

Everything in this guide was learned by executing real refactoring waves across dozens of pull requests. It reflects verified working practices, strict operational boundaries, and concrete workarounds for failure modes that actually occurred.

---

## 1. Autonomy & Execution Model

### The Autonomy Contract
1. **Continuous Momentum**: Never stop and ask whether to proceed once a wave is complete. When a batch of work feels done, that is the trigger to assess the codebase, identify the next highest-leverage targets, and launch the next wave.
2. **Strict Concurrency Cap**: Maintain a **maximum of 3 parallel subagents** (or worktrees) simultaneously. Exceeding 3 saturates memory, CPU, and CI runner queues.
3. **Offload Heavy Testing to CI**: Opening a draft PR early is preferred over running the entire 15-minute test matrix locally for every intermediate step. The developer box is shared across concurrent sessions. Run focused local unit tests, format/lint gates, push a draft PR, and let GitHub Actions run the full suite (`ruff`, `pytest`, `pytest -m integration`, `frontend`, `vitest --project browser`).
4. **Queue Hygiene & Pause Mandate**: Never let open PRs pile up or leave broken CI unresolved. Pause new refactoring waves when open PRs require rebase, conflict resolution, or CI intervention. Get all open PRs 100% green and merged before launching subsequent refactoring waves.

---

## 2. Real Gotchas & Verified Workarounds

These are not hypothetical edge cases. Every entry below was a real, repeated blocker that required a specific workaround.

### A. Repository Rule Violations on `main`
- **Symptom**: `git push origin main` fails with:
  ```
  remote: error: GH013: Repository rule violations found for refs/heads/main.
  remote: - Changes must be made through a pull request.
  ```
- **Rule**: Direct pushes to `main` are strictly blocked by repository protection rules.
- **Workaround**: Always create a feature/refactor branch (`refactor/...`, `ci/...`, `test/...`), push to the branch, and open a PR via `gh pr create`. Merge with `gh pr merge <PR_NUM> --merge --delete-branch`.

### B. Parallel Worktrees & Target Partitioning
- **Symptom**: Multiple subagents working on the main workspace collide on working tree edits, branch switches, or lockfiles.
- **Rule**: Every subagent MUST run in its own isolated worktree (`Workspace: "share"`).
- **Target Partitioning**: Ensure concurrent agents touch **completely disjoint files**:
  - *Bad*: Agent 1 extracts routes from `app.py`, Agent 2 extracts other routes from `app.py`. One will always conflict upon merging.
  - *Good*: Agent 1 extracts from `app.py` -> `sessions.py`; Agent 2 extracts from `course_html.py` -> `course_html_widgets.py`; Agent 3 decomposes `test_web.py` -> `test_web_topics.py`. Zero overlapping files.

### C. Test Monkeypatching on Composition Namespaces
- **Symptom**: Moving a builder function or dependency from `research_team/composition.py` to `research_team/wiring/` breaks integration tests with `AttributeError: module 'research_team.composition' has no attribute 'random'` or `AttributeError: module 'research_team.composition' has no attribute 'build_search_tool'`.
- **Cause**: Existing integration tests (e.g., `tests/integration/test_accept_reconciliation.py`, `tests/integration/test_approval.py`) perform direct `monkeypatch.setattr(composition, "random", ...)` or `monkeypatch.setattr(composition, "build_search_tool", ...)`.
- **Workaround**: Whenever moving functions, classes, or imports out of `composition.py`, you **must re-export them on `composition`** and include them in `__all__` (e.g., `import random as random` or `from research_team.wiring.builders import build_search_tool`).

### D. Intermittent Vitest Browser Test Flake (B186)
- **Symptom**: `CI/vitest --project browser` intermittently fails on:
  ```
  src/presentation/curriculum/course-card-sizing.browser.test.tsx:140
  expected { aspect: 'auto', ... } to match object { aspect: '3 / 2' }
  ```
- **Cause**: In headless Chrome, a broken image load event occasionally races layout computation before the aspect-ratio rule has taken effect.
- **Workaround**: When all other 4 CI gates pass (`ruff`, `pytest`, `pytest -m integration`, `frontend`) and the PR only touched Python backend files or non-presentation tests, the PR is safe to mark ready (`gh pr ready <PR_NUM>`) and merge (`gh pr merge <PR_NUM> --merge --delete-branch`).

### E. Dependabot Grouped Updates & Breaking Semver-Major Releases
- **Symptom**: A Dependabot group PR (like `toolchain`) fails CI and blocks all minor/patch updates in that ecosystem.
- **Repeated Occurrences**:
  1. **Vitest 5**: Upgraded from `4.1.11` to `5.0.1`. Vitest 5 dropped CommonJS loader compatibility and changed matchers, breaking `@testing-library/jest-dom` and `vitest-browser-react@2.2.0` (which strictly declares `peerDependencies: { vitest: "^4.0.0" }`).
  2. **JSDOM 30.1.0**: Upgraded from `30.0.1` to `30.1.0`. JSDOM 30.1.0 modified event dispatching and pointer events in `@asamuzakjp/dom-selector`, breaking Radix UI `@radix-ui/react-dropdown-menu` portal opening in `App.test.tsx:315` (`Unable to find role="menuitem" and name "Delete"`).
- **Workaround**:
  - Add ignore rules for breaking majors or regressed versions in `.github/dependabot.yml`:
    ```yaml
    ignore:
      - dependency-name: vitest
        update-types:
          - version-update:semver-major
      - dependency-name: "@vitest/*"
        update-types:
          - version-update:semver-major
      - dependency-name: jsdom
        versions: ["30.1.0"]
    ```
  - Close the blocked PR with an explanatory comment so Dependabot regenerates the group PR cleanly without the problematic package.

### F. CI Ruff Verification Checks Both Lint and Format
- **Symptom**: Local `pytest` passes, but CI `ruff` job fails.
- **Cause**: CI runs two distinct ruff checks across the *entire repository*:
  ```bash
  uv run ruff check .
  uv run ruff format --check .
  ```
- **Workaround**: Always format and check before pushing:
  ```bash
  .venv/bin/ruff format .
  .venv/bin/ruff check --fix .
  ```

---

## 3. Backlog of High-Leverage Refactoring Targets

The following modules and test suites have been identified as the highest-priority candidates for subsequent refactoring waves:

### Tier 1: Large Monolithic Implementation Files

| File | Current Lines | Extraction & Decomposition Plan |
| :--- | :--- | :--- |
| [`research_team/infrastructure/knowledge/redstring_adapter.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/knowledge/redstring_adapter.py) | **1,708** | Decompose the 1,400-line `RedstringKnowledge` class into domain-focused sub-adapters:<br>• `redstring_ingest.py` (ingest, chunking, and source tracking)<br>• `redstring_embeddings.py` (vector store and embedding generation)<br>• `redstring_consolidation.py` (entity merging and reconciliation records)<br>• `redstring_query.py` (graph search and description queries). |
| [`research_team/composition.py`](file:///home/ty/workspace/research-team/research_team/composition.py) | **1,604** | Extract remaining service wiring from `_build_application` into:<br>• `research_team/wiring/service_wiring.py` (construction of `SessionService`, `MediaCurationService`, `SocraticDialogueService`, `AskService`)<br>• `research_team/wiring/projection_wiring.py` (live feed, summary projection, and read model runners). |
| [`research_team/interfaces/web/course_html.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/course_html.py) | **1,424** | Further decompose course rendering:<br>• `course_html_markdown.py` (custom markdown parser and syntax extensions)<br>• `course_html_nav.py` (navigation table of contents and anchor rendering). |
| [`research_team/infrastructure/persistence/interaction_log.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/persistence/interaction_log.py) | **1,213** | Modularize interaction log event storage, query filtering, and CSV/JSON export handlers into separate persistence units. |
| [`research_team/interfaces/web/app.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/app.py) | **1,163** | Extract remaining specialized endpoints:<br>• `research_team/interfaces/web/system.py` (health check, tree visualization, summary/corpus rebuild endpoints)<br>• `research_team/interfaces/web/stream.py` (SSE live event streaming endpoint `/api/stream`). |
| [`research_team/domain/settings.py`](file:///home/ty/workspace/research-team/research_team/domain/settings.py) | **1,114** | Decouple settings serialization/deserialization logic from domain validation rules and entity models. |
| [`research_team/application/session_service.py`](file:///home/ty/workspace/research-team/research_team/application/session_service.py) | **1,023** | Extract turn orchestration and step command handlers into dedicated application service delegates. |

### Tier 2: Monolithic Test Suites

| Test File | Current Lines | Extraction & Decomposition Plan |
| :--- | :--- | :--- |
| [`tests/interfaces/test_web.py`](file:///home/ty/workspace/research-team/tests/interfaces/test_web.py) | **2,840** | Decompose the remaining 2,800 lines into:<br>• `test_web_sessions.py` (session CRUD, turn execution, approvals, autonomy)<br>• `test_web_projects.py` (project lifecycle, join, extraction, embeddings). |
| [`tests/infrastructure/test_redstring_adapter.py`](file:///home/ty/workspace/research-team/tests/infrastructure/test_redstring_adapter.py) | **1,667** | Decompose alongside the `redstring_adapter.py` refactoring into ingestion, consolidation, and search test modules. |
| [`tests/infrastructure/test_schema_evolution.py`](file:///home/ty/workspace/research-team/tests/infrastructure/test_schema_evolution.py) | **1,406** | Separate legacy event migration tests from version upgrade validation suites. |
| [`tests/application/test_components.py`](file:///home/ty/workspace/research-team/tests/application/test_components.py) | **1,265** | Split component test suite into per-component-type test modules matching `component_definitions.py`. |

---

## 4. Pytest Performance Optimization Strategy

1. **Shared In-Memory SQLite Databases**: Many tests open SQLite databases from disk or recreate schemas from scratch. Utilize shared in-memory databases (`:memory:`) or template database caching for fast fixtures.
2. **Selective Execution during Iteration**: When refactoring a specific domain, run only the affected test slice locally:
   ```bash
   .venv/bin/pytest tests/interfaces/test_web_topics.py -q
   ```
3. **Integration Test Tagging**: Heavy tests requiring external services (PostgreSQL, Neo4j) are tagged with `-m integration` and excluded from the standard test run. Keep this boundary strict: never introduce network or heavyweight dependencies into unit or web interface test suites.
