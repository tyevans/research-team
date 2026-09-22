# Refactoring & Codebase Health Playbook

A guide for autonomous agents and engineers working on large-scale refactoring, complexity reduction, and architectural unification in this repository.

Everything in this guide was learned by executing real refactoring waves across dozens of pull requests. It reflects verified working practices, strict operational boundaries, and concrete workarounds for failure modes that actually occurred.

---

## 1. Autonomy & Execution Model

### The Autonomy Contract
1. **Continuous Momentum**: Never stop and ask whether to proceed once a wave is complete. When a batch of work feels done, that is the trigger to assess the codebase, identify the next highest-leverage targets, and launch the next wave.
2. **Strict Concurrency Cap**: Maintain a **maximum of 1 parallel subagent** (or worktree) at any given time due to API quota limits. Exceeding 1 subagent triggers rate limit throttling and provider quota exhaustion.
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

| File | Baseline Lines | Current Lines | Status & Decomposition Plan |
| :--- | :--- | :--- | :--- |
| [`research_team/composition.py`](file:///home/ty/workspace/research-team/research_team/composition.py) | 1,604 | **695** | **Sub-700 Achieved (-909 lines)**: Extracted graph wiring (`graph_wiring.py`), executor wiring (`executor_wiring.py`), and service wiring (`service_wiring.py`). |
| [`research_team/infrastructure/config.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/config.py) | 1,157 | **1,157** | Group configuration readers by functional domain (model profiles, agent parameters, storage backends). |
| [`research_team/interfaces/web/sources.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/sources.py) | 1,015 | **500** | **Sub-500 Achieved (-515 lines)**: Decomposed into source document lifecycle (`sources.py`) and media streaming / upload sniffing / perception routes (`sources_media.py`). |
| [`research_team/wiring/application.py`](file:///home/ty/workspace/research-team/research_team/wiring/application.py) | 1,005 | **358** | **Sub-400 Achieved (-647 lines)**: Extracted application state container dataclass (`application_state.py`) from application lifecycle management (`start`/`close`). |
| [`research_team/infrastructure/knowledge/redstring_adapter.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/knowledge/redstring_adapter.py) | 1,708 | **967** | **Sub-1k Achieved (-741 lines)**: Extracted query operations (`redstring_query.py`), vector/embedding coordination (`redstring_embeddings.py`), and consolidation / entity merge operations (`redstring_consolidation.py`). |
| [`research_team/interfaces/web/dialogues.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/dialogues.py) | 1,037 | **125** | **Complete (-912 lines)**: Extracted into standalone [`ask.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/ask.py) (380 lines) and [`socratic.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/socratic.py) (708 lines) routers with `dialogues.py` as a backward-compatible facade. |
| [`research_team/interfaces/web/course_html.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/course_html.py) | 1,424 | **498** | **Sub-500 Achieved (-926 lines, -65%)**: Extracted course data models into [`course_html_models.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/course_html_models.py) (86 lines) and page rendering/dispatch into [`course_html_page.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/course_html_page.py) (284 lines). |
| [`research_team/interfaces/web/catalog.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/catalog.py) | 908 | **389** | **Sub-400 Achieved (-519 lines, -57%)**: Extracted curriculum navigation and course authoring (`curriculum.py`) and course realization lifecycle and unit inspection (`catalog_realization.py`). |
| [`research_team/knowledge/application/ontology_discovery.py`](file:///home/ty/workspace/research-team/research_team/knowledge/application/ontology_discovery.py) | 938 | **277** | **Sub-300 Achieved (-661 lines, -70%)**: Extracted prompt building, JSON parsing, verification, coordinate translation, and cross-chunk merging into [`ontology_verification.py`](file:///home/ty/workspace/research-team/research_team/knowledge/application/ontology_verification.py). |
| [`research_team/research/domain/corpus.py`](file:///home/ty/workspace/research-team/research_team/research/domain/corpus.py) | 895 | **255** | **Sub-300 Achieved (-640 lines, -71%)**: Extracted command decision validation rules and event fold logic into [`corpus_decider.py`](file:///home/ty/workspace/research-team/research_team/research/domain/corpus_decider.py). |
| [`research_team/curriculum/application/course_authoring.py`](file:///home/ty/workspace/research-team/research_team/curriculum/application/course_authoring.py) | 841 | **354** | **Sub-400 Achieved (-487 lines, -58%)**: Extracted prompt generation, component guide templates, and retry preface formatting into [`authoring_prompts.py`](file:///home/ty/workspace/research-team/research_team/curriculum/application/authoring_prompts.py). |
| [`research_team/platform/components/components.py`](file:///home/ty/workspace/research-team/research_team/platform/components/components.py) | 842 | **562** | **Sub-600 Achieved (-280 lines, -33%)**: Extracted field checkers, `Spec`, `Checker`, `Note`, and `ComponentType` into [`component_spec.py`](file:///home/ty/workspace/research-team/research_team/platform/components/component_spec.py), resolving circular dependency with `component_definitions.py`. |
| [`research_team/tenancy/application/project_sessions.py`](file:///home/ty/workspace/research-team/research_team/tenancy/application/project_sessions.py) | 832 | **395** | **Sub-400 Achieved (-437 lines, -53%)**: Extracted aggregate lifecycle operations into [`project_lifecycle.py`](file:///home/ty/workspace/research-team/research_team/tenancy/application/project_lifecycle.py) and session binding / tip catch-up / filesystem inheritance into [`project_binding.py`](file:///home/ty/workspace/research-team/research_team/tenancy/application/project_binding.py). |
| [`research_team/research/application/media_curation.py`](file:///home/ty/workspace/research-team/research_team/research/application/media_curation.py) | 807 | **416** | **Sub-420 Achieved (-391 lines, -48%)**: Extracted prompting templates, candidate caps, and model response parsers into [`media_curation_prompts.py`](file:///home/ty/workspace/research-team/research_team/research/application/media_curation_prompts.py). |
| [`research_team/session/application/session_service.py`](file:///home/ty/workspace/research-team/research_team/session/application/session_service.py) | 1,056 | **779** | **Sub-780 Achieved (-277 lines, -26%)**: Extracted session inspection/diffing (`session_inspection.py`) and turn execution / fork lifecycle into [`turn_runner.py`](file:///home/ty/workspace/research-team/research_team/session/application/turn_runner.py) (`TurnRunner`, `fork_session`). |
| [`research_team/interfaces/web/app.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/app.py) | 1,163 | **534** | **Sub-550 Achieved (-629 lines, -54%)**: Extracted middleware (`middleware.py`), static assets serving and console mounting (`statics.py`), global art route (`art.py`), and project/session reader closures (`app_readers.py`). |
| [`research_team/infrastructure/persistence/ontology_read_models.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/persistence/ontology_read_models.py) | 866 | **495** | **Sub-500 Achieved (-371 lines, -43%)**: Extracted entity definition row, store, projection, and runner into [`definition_read_models.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/persistence/definition_read_models.py). |
| [`research_team/research/domain/topic.py`](file:///home/ty/workspace/research-team/research_team/research/domain/topic.py) | 815 | **493** | **Sub-500 Achieved (-322 lines, -40%)**: Extracted command decision validation rules and event fold logic into [`topic_decider.py`](file:///home/ty/workspace/research-team/research_team/research/domain/topic_decider.py). |
| [`research_team/interfaces/web/knowledge.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/knowledge.py) | 812 | **502** | **Sub-510 Achieved (-310 lines, -38%)**: Extracted media proposal endpoints/models into [`media_proposals.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/media_proposals.py) (317 lines) and ontology discovery endpoints/models into [`ontology.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/ontology.py) (201 lines). |
| [`research_team/infrastructure/persistence/event_store.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/persistence/event_store.py) | 868 | **639** | **Sub-650 Achieved (-229 lines, -26%)**: Extracted aggregate repository factory functions into [`aggregate_repositories.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/persistence/aggregate_repositories.py) (322 lines). |
| [`research_team/platform/components/component_definitions.py`](file:///home/ty/workspace/research-team/research_team/platform/components/component_definitions.py) | 792 | **541** | **Sub-550 Achieved (-251 lines, -32%)**: Extracted normalizers, validators, and warn hooks into [`component_normalizers.py`](file:///home/ty/workspace/research-team/research_team/platform/components/component_normalizers.py) (301 lines). |
| [`research_team/dialogue/application/socratic.py`](file:///home/ty/workspace/research-team/research_team/dialogue/application/socratic.py) | 776 | **559** | **Sub-560 Achieved (-217 lines, -28%)**: Extracted data models, exceptions, registry cache, and protocols into [`socratic_models.py`](file:///home/ty/workspace/research-team/research_team/dialogue/application/socratic_models.py) (283 lines). |
| [`research_team/interfaces/web/topics.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/topics.py) | 757 | **524** | **Sub-530 Achieved (-233 lines, -31%)**: Extracted topic dispatch queue endpoints, models (`NewDispatch`, `BulkDispatch`), and worker roster routes into [`topic_dispatch.py`](file:///home/ty/workspace/research-team/research_team/interfaces/web/topic_dispatch.py) (228 lines). |
| [`research_team/tenancy/domain/tenant.py`](file:///home/ty/workspace/research-team/research_team/tenancy/domain/tenant.py) | 749 | **451** | **Sub-460 Achieved (-298 lines, -40%)**: Extracted command decision validation (`decide`) and event evolution rules (`evolve`) into [`tenant_decider.py`](file:///home/ty/workspace/research-team/research_team/tenancy/domain/tenant_decider.py) (379 lines), matching the aggregate decider pattern established by `Corpus` and `Topic`. |
| [`research_team/infrastructure/persistence/corpus_read_models.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/persistence/corpus_read_models.py) | 736 | **297** | **Sub-300 Achieved (-439 lines, -60%)**: Extracted table row models and conversions into [`corpus_rows.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/persistence/corpus_rows.py) (246 lines) and event projection logic into [`corpus_projection.py`](file:///home/ty/workspace/research-team/research_team/infrastructure/persistence/corpus_projection.py) (243 lines). |

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
