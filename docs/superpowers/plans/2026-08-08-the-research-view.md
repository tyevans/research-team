# The Research View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A top-level `#/p/:id/research` page that reads a project's topics, documents and knowledge graph, manages topic status, and seeds topics from a subject line.

**Architecture:** Read-side composition. Two new application ports (`TopicReadPort`, `GraphReadPort`) with infrastructure adapters, new FastAPI routes on the existing `create_app`, and a new `src/presentation/research/` feature folder in the console. No new aggregate, no new event, no new domain command.

**Tech Stack:** Python 3.13 / FastAPI / pytest / `eventsource` aggregates / redstring `GraphStore`. React 19 / TypeScript / Vite / Vitest / TanStack Query / zustand / wouter. New deps: `react-force-graph-2d`, `@tanstack/react-virtual`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-08-the-research-view-design.md`. Read it before Task 1.
- **Worktree:** all work happens in `.claude/worktrees/research-view` on branch `worktree-research-view`. Never `git checkout` another branch.
- **TDD is mandatory.** Every task writes a failing test, runs it to see it fail for the *stated* reason, then implements. A test that passes before implementation is a broken test — fix the test, do not proceed.
- **Layering (frontend), enforced by `eslint.config.js` `no-restricted-imports`:** `domain/` → `application/` → `infrastructure/` → `presentation/` → `app/`, dependencies inward only. `domain/` imports no framework. Wire spellings (snake_case JSON keys) appear ONLY in `src/infrastructure/http/dto.ts` and `mappers.ts`.
- **Layering (Python):** `domain/` knows nothing of `application/`; `application/` declares Protocols, `infrastructure/` implements them; `interfaces/web/` composes. Presenters build plain dicts in `research_team/interfaces/web/presenters.py` — routes never build response dicts inline.
- **Styling:** new CSS goes in `frontend/src/styles/research.css`, imported from `index.css`. It defines **no colour, size or radius literals** — only `var(--…)` tokens from `tokens.css`. A second literal hex is a second palette.
- **Bundle budget:** `frontend/scripts/check-size.mjs` gates gzipped chunk sizes. Current `total: 180`. Only Task 14 may raise it, and its commit message must say what was bought.
- **Commit style:** lowercase conventional prefix, then a sentence in the repo's voice explaining *why*. Look at `git log` for the register. Every commit ends with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```
- **Comments:** this codebase comments *why*, not *what*, in full prose sentences. Match that density. Do not write `# loop over topics`.
- **Never** weaken an assertion to make a test pass. Never add `# type: ignore` without a sentence saying why.

## Test Commands

| Scope | Command | Working dir |
|---|---|---|
| One Python test | `uv run pytest tests/path::test_name -v` | repo root |
| Python suite | `uv run pytest -q` | repo root |
| One frontend file | `npm test -- src/path/file.test.ts` | `frontend/` |
| Frontend suite | `npm test` | `frontend/` |
| Lint + types + size | `npm run verify` | `frontend/` |

Baseline at plan time: **1590 Python tests, 324 frontend tests, all green.**

## File Structure

**Python — created**

| File | Responsibility |
|---|---|
| `research_team/application/topic_read.py` | `TopicReadPort` Protocol, `TopicView`, `TopicDetail`, `SubQuestionView` |
| `research_team/application/graph_read.py` | `GraphReadPort` Protocol, `GraphEntity`, `GraphRelationship`, `EntityPage`, `Neighborhood`, `MAX_NEIGHBORHOOD_DEPTH` |
| `research_team/application/project_graphs.py` | `ProjectGraphs` — the one owner of an open graph store per project |
| `research_team/infrastructure/persistence/topic_reader.py` | `ProjectTopicReader` implementing `TopicReadPort` |
| `research_team/infrastructure/knowledge/graph_reader.py` | `ProjectGraphReader` implementing `GraphReadPort` |
| `research_team/application/topic_seeding.py` | `TopicSeeder`, `SEEDING_PROMPT` |
| `research_team/interfaces/web/seeding.py` | `SeedingActivity` — provisional per-project seeding state |
| `tests/application/test_topic_read.py`, `test_graph_read.py`, `test_project_graphs.py`, `test_topic_seeding.py` | port-level tests |

**Python — modified**

| File | Change |
|---|---|
| `research_team/interfaces/web/app.py` | new `create_app` params + 9 routes |
| `research_team/interfaces/web/presenters.py` | `topic_view`, `topic_detail_view`, `entity_view`, `relationship_view`, `neighborhood_view`, `seeding_view` |
| `research_team/composition.py` | build `ProjectGraphs`; `open_graph` borrows its store; expose new services on `Application` |
| `web.py` | pass `corpus`, `topics`, `graphs`, `seeding` into `create_app` |
| `tests/interfaces/test_web.py` | route tests |

**Frontend — created**

| File | Responsibility |
|---|---|
| `src/domain/research/topic.ts` | `TopicView`, `TopicStatus`, `LEGAL_STATUSES`, `needsAttention`, `bySeverity` |
| `src/domain/knowledge/graph.ts` | `GraphView`, `emptyGraph`, `expand`, `focus` — the merge fold |
| `src/application/research/graph-store.ts` | zustand store holding a `GraphView` + expansion |
| `src/infrastructure/http/topic-repository.ts` | `HttpTopicRepository` |
| `src/infrastructure/http/graph-repository.ts` | `HttpGraphRepository` |
| `src/presentation/research/ResearchView.tsx` | the page shell + region layout |
| `src/presentation/research/TopicList.tsx` | topic rows + attention |
| `src/presentation/research/TopicStatusDialog.tsx` | close/supersede with required justification |
| `src/presentation/research/SubQuestions.tsx` | add/resolve |
| `src/presentation/research/SeedPanel.tsx` | subject input + run state |
| `src/presentation/research/DocumentList.tsx` | virtualized listing |
| `src/presentation/research/DocumentReader.tsx` | span reader |
| `src/presentation/research/GraphPane.tsx` | lazy boundary + controls |
| `src/presentation/research/GraphCanvas.tsx` | the `react-force-graph-2d` wrapper (lazy-loaded) |
| `src/styles/research.css` | tokens-only styling |

**Frontend — modified:** `routing/routes.ts`, `app/App.tsx`, `app/container.ts`, `application/ports/repositories.ts`, `application/queries/keys.ts`, `infrastructure/http/dto.ts`, `infrastructure/http/mappers.ts`, `src/styles/index.css`, `vite.config.ts`, `scripts/check-size.mjs`, `package.json`, `src/presentation/course/CourseView.tsx` (a link across).

---

# Slice 1 — Topics, read

### Task 1: `TopicReadPort` and its view types

**Files:**
- Create: `research_team/application/topic_read.py`
- Test: `tests/application/test_topic_read.py`

**Interfaces:**
- Consumes: `TopicSummary` from `research_team/application/topics.py`; `TopicAttention` from `research_team/application/topic_attention.py`; `TopicStatus`, `TopicState` from `research_team/domain/topic.py`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class TopicView:
      summary: TopicSummary
      attention: TopicAttention
      @property
      def needs_attention(self) -> bool: ...

  @dataclass(frozen=True)
  class SubQuestionView:
      key: str
      question: str
      answer: str | None
      @property
      def resolved(self) -> bool: ...

  @dataclass(frozen=True)
  class TopicDetail:
      view: TopicView
      rationale: str
      scope: str
      sub_questions: tuple[SubQuestionView, ...]
      source_ids: tuple[str, ...]
      findings: tuple[str, ...]
      contested: bool

  class TopicReadPort(Protocol):
      async def list_topics(self) -> list[TopicView]: ...
      async def read_topic(self, topic_id: UUID) -> TopicDetail | None: ...
  ```

Read `research_team/application/corpus_read.py` first — this file is its sibling and should read like it, including a module docstring explaining why the project is not a parameter and why this is a second port rather than four more methods on `TopicPort`.

- [ ] **Step 1: Write the failing test**

`tests/application/test_topic_read.py`. Build a real `Topic` aggregate via `build_topic_repository`, execute `OpenTopic`, and assert the view shapes. Follow the fixtures in `tests/application/` for store setup.

```python
async def test_a_view_carries_both_the_summary_and_why_it_needs_attention(topic_reader, opened_topic):
    """The list is ranked on attention, so the thing that ranks it travels with the row.

    A caller that had to make a second call per topic to learn why it was
    flagged would either make N calls or skip the flag entirely.
    """
    views = await topic_reader.list_topics()

    assert [view.summary.question for view in views] == ["Does spacing help?"]
    # Never investigated is a real trigger on a freshly opened topic, so this
    # is the flag arriving through the port rather than a contrived one.
    assert "topic.never_investigated" in views[0].attention.triggers
    assert views[0].needs_attention is True


async def test_an_unknown_topic_reads_as_none_rather_than_raising(topic_reader):
    """Absence is the expected case for a hand-edited URL, not a failure."""
    assert await topic_reader.read_topic(uuid4()) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/application/test_topic_read.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_team.application.topic_read'`

- [ ] **Step 3: Write `topic_read.py`**

Protocol + dataclasses only — no implementation yet. The test also needs `ProjectTopicReader` (Task 2), so expect the test to still fail after this step with `ImportError` on the reader. That is the correct intermediate state; do not stub the reader here.

- [ ] **Step 4: Commit**

```bash
git add research_team/application/topic_read.py tests/application/test_topic_read.py
git commit -m "feat: a port for reading topics, separate from the agent's

TopicPort's four methods are four tools, and its meaning is 'what the model
may do'. Read shapes there would be wired into tools by the next reader.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `ProjectTopicReader`

**Files:**
- Create: `research_team/infrastructure/persistence/topic_reader.py`
- Test: `tests/application/test_topic_read.py` (the tests from Task 1 now go green)

**Interfaces:**
- Consumes: `TopicReadPort`, `TopicView`, `TopicDetail` (Task 1); `AggregateRepository[Topic]` from `build_topic_repository` in `research_team/infrastructure/persistence/event_store.py:79`; `attention_for(state, corpus, *, at_position=None, triggers=REGISTRY)` from `topic_attention.py:476`; the existing `TopicRunner`/topic queue used by `RepositoryTopics` in `research_team/infrastructure/agent/topic_tools.py:73`.
- Produces: `ProjectTopicReader(queue, repository, corpus_facts, project_id)` implementing `TopicReadPort`.

Model it on `research_team/infrastructure/persistence/corpus_reader.py:25`. `attention_for` needs `CorpusFacts` — get it the same way `topic_attention`'s existing callers do; read `research_team/application/auto_research.py` to see how the driver assembles it, and reuse that path rather than inventing a second one.

- [ ] **Step 1: Run the Task 1 tests to confirm they fail on the missing reader**

Run: `uv run pytest tests/application/test_topic_read.py -v`
Expected: FAIL with `ImportError`/`AttributeError` naming `ProjectTopicReader`.

- [ ] **Step 2: Implement `ProjectTopicReader`**

`list_topics` reads the project's live *and* closed topics — the page shows both, so do not filter on `is_live`. `read_topic` loads the aggregate and returns `None` when its state is `"new"` (never opened) or when its `project_id` does not match this reader's, which is the guard that stops one project reading another's topic by id.

- [ ] **Step 3: Run to verify pass**

Run: `uv run pytest tests/application/test_topic_read.py -v` → PASS

- [ ] **Step 4: Add the cross-project guard test**

```python
async def test_a_topic_belonging_to_another_project_reads_as_none(reader_for_other_project, opened_topic):
    """Project scoping is the reader's job, not the caller's.

    Every port here is bound to one project at construction precisely so a
    caller cannot pass a different id; reading by topic id is the one call
    that could sidestep that, so it checks.
    """
    assert await reader_for_other_project.read_topic(opened_topic) is None
```

- [ ] **Step 5: Run to verify pass, then run the application suite**

Run: `uv run pytest tests/application -q` → PASS

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/persistence/topic_reader.py tests/application/test_topic_read.py
git commit -m "feat: read a project's topics with their attention attached

Attention is computed on read and never stored, so the row and the reason
it is flagged are one query rather than two.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Topic list and detail routes

**Files:**
- Modify: `research_team/interfaces/web/presenters.py`, `research_team/interfaces/web/app.py`, `research_team/composition.py`, `web.py`
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: `ProjectTopicReader` (Task 2); `create_app(...)` at `app.py:209`; `_require_project` at `app.py:372`; `source_view` at `presenters.py:444` as the presenter template.
- Produces: `create_app(..., topics: TopicRunner | None = None)`; routes `GET /api/projects/{project_id}/topics` and `GET /api/projects/{project_id}/topics/{topic_id}`; presenters `topic_view(view) -> dict` and `topic_detail_view(detail) -> dict`.

Wire shape for one topic row — later tasks and the frontend DTO depend on these exact keys:

```json
{
  "topic_id": "…", "question": "…", "status": "open",
  "sources": 4, "findings": 2, "open_sub_questions": 1,
  "triggers": ["topic.never_investigated"],
  "needs_attention": true, "is_blocked": false
}
```

`topic_detail_view` is that object plus `"rationale"`, `"scope"`, `"sub_questions": [{"key","question","answer","resolved"}]`, `"source_ids"`, `"findings"`, `"contested"`.

Add a `_topic_reader(project_id)` helper beside `_reader` at `app.py:466`, raising `HTTPException(503, "no topic read model is configured")` when `topics is None`, so an unwired build is explicit rather than a 500.

- [ ] **Step 1: Write the failing route tests**

In `tests/interfaces/test_web.py`, beside the corpus block (~line 1343). Mirror `_project_with_sources` with a `_project_with_topics` helper.

```python
async def test_listing_topics_reports_status_counts_and_triggers(client):
    project_id, _ = await _project_with_topics(client)

    response = await client.get(f"/api/projects/{project_id}/topics")

    assert response.status_code == 200
    row = response.json()[0]
    assert row["question"] == "Does spacing help?"
    assert row["status"] == "open"
    assert row["needs_attention"] is True
    assert "topic.never_investigated" in row["triggers"]


async def test_reading_a_topic_adds_what_the_row_leaves_out(client):
    project_id, topic_id = await _project_with_topics(client)

    body = (await client.get(f"/api/projects/{project_id}/topics/{topic_id}")).json()

    assert body["rationale"] == "because it is the whole question"
    assert body["sub_questions"] == []
    assert body["source_ids"] == []


async def test_an_unknown_topic_is_a_404(client):
    project_id, _ = await _project_with_topics(client)

    response = await client.get(f"/api/projects/{project_id}/topics/{uuid4()}")

    assert response.status_code == 404


async def test_an_unknown_project_is_a_404_on_both_topic_routes(client):
    missing = uuid4()

    assert (await client.get(f"/api/projects/{missing}/topics")).status_code == 404
    assert (await client.get(f"/api/projects/{missing}/topics/{uuid4()}")).status_code == 404
```

Update the `app_and_client` fixture (line ~57) to pass `topics=application.topics`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/interfaces/test_web.py -k topic -v`
Expected: FAIL with 404s from FastAPI (no such route registered).

- [ ] **Step 3: Add the presenters**

- [ ] **Step 4: Add the routes and the `topics` parameter**

- [ ] **Step 5: Wire `topics=application.topics` in `web.py`**

Also pass `corpus=application.corpus`, which `web.py` currently omits — the shipped entrypoint 503s on the source routes today, and the document browser in Slice 3 needs it. Note this in the commit message; it is a real bug fix, not incidental.

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/interfaces/test_web.py -q` → PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: topics over HTTP, for the first time

A full aggregate with eleven commands has been reachable only by an agent.
This is the read half. It also wires the corpus reader into web.py, which
had been left out -- the source routes have been 503ing in the shipped
entrypoint while the tests passed against a fixture that wired it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The `research` route and an empty page

**Files:**
- Modify: `frontend/src/presentation/routing/routes.ts`, `frontend/src/app/App.tsx`, `frontend/src/styles/index.css`
- Create: `frontend/src/presentation/research/ResearchView.tsx`, `frontend/src/styles/research.css`
- Test: `frontend/src/presentation/routing/routes.test.ts` (exists — extend it)

**Interfaces:**
- Consumes: `Route` union and `parseRoute` in `routes.ts`; `CurrentView` switch in `App.tsx`.
- Produces: `{ readonly name: 'research'; readonly id: ProjectId }` on `Route`; `researchHref(projectId: ProjectId): string` returning `#/p/<id>/research`; `<ResearchView projectId={...} />`.

- [ ] **Step 1: Write the failing route test**

```typescript
it('parses a research route', () => {
  // Sits under the project the way `course` does: what it shows outlives any
  // one session, so it is keyed the way the material is stored.
  expect(parseRoute('#/p/abc/research')).toEqual({ name: 'research', id: ProjectId('abc') })
})

it('builds a research href', () => {
  expect(researchHref(ProjectId('abc'))).toBe('#/p/abc/research')
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/presentation/routing/routes.test.ts`
Expected: FAIL — `researchHref` is not exported.

- [ ] **Step 3: Add the variant, the parse branch and the href**

The parse branch goes beside the `course` branch: `parts[0] === 'p' && parts[1] && parts[2] === 'research'`.

- [ ] **Step 4: Run to verify pass**

- [ ] **Step 5: Add `ResearchView` rendering a heading and four empty region shells, add the `case 'research'` to `CurrentView`, create `research.css`, import it from `index.css`**

- [ ] **Step 6: Run the frontend suite and verify**

Run: `npm test && npm run verify` → PASS

- [ ] **Step 7: Commit**

---

### Task 5: The topics pane

**Files:**
- Create: `frontend/src/domain/research/topic.ts` + `.test.ts`
- Create: `frontend/src/presentation/research/TopicList.tsx` + `.test.tsx`
- Create: `frontend/src/infrastructure/http/topic-repository.ts`
- Modify: `dto.ts`, `mappers.ts`, `ports/repositories.ts`, `app/container.ts`, `queries/keys.ts`, `ResearchView.tsx`, `research.css`

**Interfaces:**
- Consumes: the wire shape from Task 3; `HttpExtractionRepository` in `project-repository.ts` as the repository template; `ExtractionPane.tsx`/`.test.tsx` as the pane template.
- Produces:
  ```typescript
  // domain/research/topic.ts
  export type TopicStatus = 'open' | 'investigating' | 'answered' | 'not_pursuing' | 'superseded'
  export const CLOSED_STATUSES: readonly TopicStatus[]
  export interface TopicView {
    readonly topicId: TopicId
    readonly question: string
    readonly status: TopicStatus
    readonly sources: number
    readonly findings: number
    readonly openSubQuestions: number
    readonly triggers: readonly string[]
    readonly needsAttention: boolean
    readonly isBlocked: boolean
  }
  export const isClosed: (topic: TopicView) => boolean
  export const byUrgency: (a: TopicView, b: TopicView) => number

  // application/ports/repositories.ts
  export interface TopicRepository {
    list(projectId: ProjectId): Promise<readonly TopicView[]>
    read(projectId: ProjectId, topicId: TopicId): Promise<TopicDetail>
  }

  // application/queries/keys.ts
  topics: (project: ProjectId) => ['topics', project] as const
  topic: (project: ProjectId, topic: TopicId) => ['topic', project, topic] as const
  ```

`byUrgency` is the pure bit worth testing hard: blocked first, then needing attention, then live, then closed; ties broken by question text so the order is stable across refetches. A list that reorders on every poll is unreadable.

- [ ] **Step 1: Write the failing domain test for `byUrgency` and `isClosed`**

```typescript
it('puts blocked topics above merely flagged ones', () => {
  const blocked = topic({ question: 'b', isBlocked: true, needsAttention: true })
  const flagged = topic({ question: 'a', isBlocked: false, needsAttention: true })

  expect([flagged, blocked].sort(byUrgency)).toEqual([blocked, flagged])
})

it('orders ties by question so a refetch does not reshuffle the list', () => {
  // Two rows with identical urgency have no natural order, and a sort that
  // leaves them in arrival order will swap them whenever the server's own
  // ordering shifts. The list is read top-down; it must hold still.
  const a = topic({ question: 'a' })
  const b = topic({ question: 'b' })

  expect([b, a].sort(byUrgency)).toEqual([a, b])
})
```

- [ ] **Step 2: Run to verify failure** — `npm test -- src/domain/research/topic.test.ts`

- [ ] **Step 3: Implement `domain/research/topic.ts`**

- [ ] **Step 4: Run to verify pass**

- [ ] **Step 5: Add the DTO, mapper, repository, port entry, container registration and query keys**

`topicDto` in `dto.ts` is where `needs_attention` → `needsAttention` happens, and the ONLY place those snake_case spellings may appear.

- [ ] **Step 6: Write the failing `TopicList.test.tsx`**

Render with a stubbed repository; assert questions render, triggers render under the question that carries them, and that a blocked topic sorts first.

- [ ] **Step 7: Run to verify failure, implement `TopicList.tsx`, mount it in `ResearchView`, run to verify pass**

- [ ] **Step 8: `npm run verify`, then commit**

---

# Slice 2 — Topic management

### Task 6: Status, sub-question routes

**Files:**
- Modify: `research_team/interfaces/web/app.py`, `presenters.py`
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: `SetTopicStatus(to_status, justification)`, `AddSubQuestion(key, question)`, `ResolveSubQuestion(key, answer)` from `research_team/domain/topic.py:226,284`; `AggregateRepository[Topic]` load/execute/save, pattern at `tests/interfaces/test_web.py:1368`.
- Produces:
  - `POST /api/projects/{pid}/topics/{tid}/status`, body `{"to_status": …, "justification": …}`
  - `POST /api/projects/{pid}/topics/{tid}/sub-questions`, body `{"key": …, "question": …}`
  - `POST /api/projects/{pid}/topics/{tid}/sub-questions/{key}/resolve`, body `{"answer": …}`
  - All three return the updated `topic_detail_view`.

Pydantic bodies with `justification: str = Field(min_length=1)` so blank is a 422 from the transport, before the aggregate is loaded. `CommandRejectedError` maps to 409.

**These are human-only. Do not add a tool, and do not add anything to `TopicPort`.**

- [ ] **Step 1: Write the failing tests**

```python
async def test_closing_a_topic_records_the_justification(client):
    project_id, topic_id = await _project_with_topics(client)

    response = await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "answered", "justification": "the sources agree"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"


async def test_a_blank_justification_is_refused(client):
    """The aggregate went out of its way to make an unexplained status change
    impossible, and a transport that supplied a default to get past it would
    quietly undo that."""
    project_id, topic_id = await _project_with_topics(client)

    response = await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "answered", "justification": "   "},
    )

    assert response.status_code == 422


async def test_reopening_an_answered_topic_is_allowed(client):
    """`decide` rejects only a no-op transition, so this is legal, and a
    reader who closed a topic too early needs it."""
    project_id, topic_id = await _project_with_topics(client)
    await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "answered", "justification": "done"},
    )

    response = await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "open", "justification": "new material arrived"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "open"


async def test_a_sub_question_can_be_added_and_resolved(client):
    project_id, topic_id = await _project_with_topics(client)

    await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/sub-questions",
        json={"key": "motor", "question": "Does it hold for motor skills?"},
    )
    body = (
        await client.post(
            f"/api/projects/{project_id}/topics/{topic_id}/sub-questions/motor/resolve",
            json={"answer": "Yes, with a smaller effect."},
        )
    ).json()

    assert body["sub_questions"][0]["resolved"] is True
    assert body["sub_questions"][0]["answer"] == "Yes, with a smaller effect."
```

A blank justification must fail at 422 — if `Field(min_length=1)` lets `"   "` through, strip in a validator. Do not relax the test.

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement the three routes**
- [ ] **Step 4: Run to verify pass, then `uv run pytest -q`**
- [ ] **Step 5: Commit**

---

### Task 7: The status dialog and sub-questions UI

**Files:**
- Create: `frontend/src/presentation/research/TopicStatusDialog.tsx` + `.test.tsx`, `SubQuestions.tsx` + `.test.tsx`
- Modify: `topic-repository.ts`, `ports/repositories.ts`, `TopicList.tsx`, `research.css`

**Interfaces:**
- Consumes: routes from Task 6; `WorkerDrawer.tsx` for the focus-trap pattern — commit `d5f9b64` fixed exactly this and the dialog must not reintroduce it.
- Produces: `TopicRepository.setStatus(projectId, topicId, toStatus, justification)`, `.addSubQuestion(...)`, `.resolveSubQuestion(...)`.

- [ ] **Step 1: Write the failing dialog test**

```tsx
it('will not submit without a justification', async () => {
  render(<TopicStatusDialog topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.click(screen.getByRole('button', { name: /answered/i }))

  expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
})

it('traps focus while it is open', async () => {
  // The drawer shipped without this and it had to be fixed after the fact.
  render(<TopicStatusDialog topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.tab()
  expect(document.activeElement).not.toBe(document.body)
})
```

- [ ] **Step 2–5: verify failure, implement, verify pass, `npm run verify`, commit**

---

# Slice 3 — Documents

### Task 8: The document list

**Files:**
- Create: `frontend/src/presentation/research/DocumentList.tsx` + `.test.tsx`, `DocumentReader.tsx` + `.test.tsx`
- Modify: `package.json`, `dto.ts`, `mappers.ts`, `ports/repositories.ts`, `container.ts`, `keys.ts`, `ResearchView.tsx`, `research.css`, `scripts/check-size.mjs`

**Interfaces:**
- Consumes: existing `GET /api/projects/{id}/sources` and `.../sources/{sid}?start&end` (already wired in `web.py` as of Task 3); `source_view` keys `source_id, char_count, sha256, uri, title, published_at, note`.
- Produces: `DocumentRepository.list(projectId)`, `.read(projectId, sourceId, range?)`.

Add `@tanstack/react-virtual@^3.14.9` (~7 kB gzip). It lands in the existing `vendor-` chunk; raise `vendor-` from 36 to 44 in `check-size.mjs` and `total` from 180 to 188 in this commit, with a note.

**Dropped documents stay in the listing** with their `dropped_reason` shown. `source_view` does not currently emit `dropped_reason` and `list_documents` filters dropped documents out — so this needs a backend change first: a `?include_dropped=true` query parameter on the list route and `dropped_reason` added to `source_view`. Write that test first:

```python
async def test_dropped_sources_can_be_listed_with_their_reason(client):
    """The corpus keeps dropped documents deliberately. A browser that hid
    them would misreport what the project holds."""
    project_id = await _project_with_a_dropped_source(client)

    rows = (await client.get(f"/api/projects/{project_id}/sources?include_dropped=true")).json()

    assert rows[0]["dropped_reason"] == "superseded by a later edition"
```

The default stays `false` so the agent's `list_sources` tool is unchanged.

- [ ] **Step 1: Write the failing Python test above; verify failure; implement; verify pass; commit**
- [ ] **Step 2: Write the failing `DocumentList.test.tsx`** — asserts a dropped row renders its reason and is visually marked
- [ ] **Step 3–6: verify failure, implement with `useVirtualizer`, verify pass, `npm run verify`, commit**

---

# Slice 4 — The graph, read

### Task 9: `ProjectGraphs` — one owner of an open graph store

**Files:**
- Create: `research_team/application/project_graphs.py`, `tests/application/test_project_graphs.py`
- Modify: `research_team/composition.py`

**Interfaces:**
- Consumes: `build_graph_store(config.graph_store())` from `infrastructure/knowledge/stores.py:15`; `rebuild_graph(store, feed=…, project_id=…)` from `infrastructure/knowledge/rebuild.py`; `open_graph` at `composition.py:604`.
- Produces:
  ```python
  class ProjectGraphs:
      async def open(self, project_id: UUID) -> GraphStore: ...
      async def close(self, project_id: UUID) -> None: ...
      async def close_all(self) -> None: ...
  ```

**Why this task exists.** The spec assumed a graph store to read from. Today one is built *inside* `open_graph` and exists only while a project is attached to the executor. A read route cannot rely on that, and a second store rebuilt independently would go stale the moment extraction wrote to the attached one — you would extract, open the graph browser, and see nothing new. So `ProjectGraphs` becomes the single owner: it opens-and-caches one store per project, and `open_graph` borrows from it instead of building its own.

`open` is idempotent and must be safe under concurrent callers — guard the per-project build with an `asyncio.Lock` so two simultaneous opens do not both run `rebuild_graph`. `close` is called on project deletion; `close_all` on shutdown.

`open_graph` changes from `store = build_graph_store(...)` + `ensure_schema` + `rebuild_graph` to `store = await graphs.open(target_project_id)`, and its `except` branch no longer closes the store — the cache owns its lifetime now. Read `open_graph`'s docstring about atomicity and update it to say so.

- [ ] **Step 1: Write the failing tests**

```python
async def test_opening_the_same_project_twice_returns_the_same_store(graphs):
    """Attachment and the read routes must see one graph.

    Two stores rebuilt separately are correct at the instant they are built
    and wrong immediately after: extraction writes to one, and the other
    keeps answering from a snapshot of the past.
    """
    first = await graphs.open(project_id)
    second = await graphs.open(project_id)

    assert first is second


async def test_concurrent_opens_rebuild_only_once(graphs, counting_rebuild):
    await asyncio.gather(*(graphs.open(project_id) for _ in range(5)))

    assert counting_rebuild.calls == 1


async def test_closing_evicts_so_a_later_open_rebuilds(graphs, counting_rebuild):
    await graphs.open(project_id)
    await graphs.close(project_id)
    await graphs.open(project_id)

    assert counting_rebuild.calls == 2
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement `ProjectGraphs`**
- [ ] **Step 4: Run to verify pass**
- [ ] **Step 5: Rewire `open_graph` to borrow, and evict on project delete**
- [ ] **Step 6: Run the full Python suite** — `uv run pytest -q`. This touches attachment, so knowledge and composition tests are the ones to watch. Expected: 1590+ passing, 0 failures.
- [ ] **Step 7: Commit**

---

### Task 10: `GraphReadPort` and `ProjectGraphReader`

**Files:**
- Create: `research_team/application/graph_read.py`, `research_team/infrastructure/knowledge/graph_reader.py`, `tests/application/test_graph_read.py`

**Interfaces:**
- Consumes: `GraphStore.find_entities(tenant_id, *, name=None, entity_type=None, limit=None, after=None)`, `.neighbors(entity_id, tenant_id, *, depth=1, relationship_types=None)`, `.get_relationships_for(entity_ids, tenant_id, *, direction='both', relationship_types=None)`; `ProjectGraphs` (Task 9).
- Produces:
  ```python
  MAX_NEIGHBORHOOD_DEPTH = 2

  @dataclass(frozen=True)
  class GraphEntity:
      entity_id: str
      name: str
      entity_type: str

  @dataclass(frozen=True)
  class GraphRelationship:
      source_id: str
      target_id: str
      relationship_type: str

  @dataclass(frozen=True)
  class EntityPage:
      entities: tuple[GraphEntity, ...]
      next_after: str | None

  @dataclass(frozen=True)
  class Neighborhood:
      root: GraphEntity
      entities: tuple[GraphEntity, ...]
      relationships: tuple[GraphRelationship, ...]

  class GraphReadPort(Protocol):
      async def find_entities(self, *, name=None, entity_type=None,
                              limit=100, after=None) -> EntityPage: ...
      async def neighborhood(self, entity_id: str, *, depth: int = 1) -> Neighborhood | None: ...
  ```

`neighborhood` resolves relationships in **one** `get_relationships_for` call over the returned entity set, and returns only relationships whose *both* ends are in that set — a dangling edge to a node the client was not given is an edge it cannot draw.

Depth is clamped to `MAX_NEIGHBORHOOD_DEPTH` in the port implementation, not only at the route. `neighbors(depth=3)` on a hub can return most of the graph, and a route is not the last place that can ask.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_neighborhood_carries_the_edges_among_what_it_returned(graph_reader, seeded_graph):
    """One call, not N. A client that had to ask how its own result is wired
    would issue a request per node and draw a graph that flickers into shape."""
    hood = await graph_reader.neighborhood(prandtl_id, depth=1)

    assert {entity.name for entity in hood.entities} >= {"Theodore von Kármán", "Göttingen"}
    assert any(edge.relationship_type == "advised" for edge in hood.relationships)


async def test_edges_to_entities_outside_the_neighborhood_are_dropped(graph_reader, seeded_graph):
    """An edge whose other end was not returned is one the caller cannot draw."""
    hood = await graph_reader.neighborhood(prandtl_id, depth=1)

    returned = {entity.entity_id for entity in hood.entities} | {hood.root.entity_id}
    for edge in hood.relationships:
        assert edge.source_id in returned and edge.target_id in returned


async def test_depth_is_clamped_by_the_port_not_only_the_route(graph_reader, deep_graph):
    """A route is not the last thing that can ask for depth 5."""
    deep = await graph_reader.neighborhood(root_id, depth=5)
    capped = await graph_reader.neighborhood(root_id, depth=MAX_NEIGHBORHOOD_DEPTH)

    assert {entity.entity_id for entity in deep.entities} == {
        entity.entity_id for entity in capped.entities
    }


async def test_an_unknown_entity_reads_as_none(graph_reader, seeded_graph):
    assert await graph_reader.neighborhood("no-such-entity") is None
```

Use `InMemoryGraphStore` directly and seed it with `upsert_entities`/`upsert_relationships` — no LLM, no extraction, no `ingest`.

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement both files**
- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/application/test_graph_read.py -v`
- [ ] **Step 5: Commit**

---

### Task 11: Graph routes

**Files:**
- Modify: `app.py`, `presenters.py`, `composition.py`, `web.py`
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Produces: `GET /api/projects/{pid}/graph/entities?name=&entity_type=&limit=&after=`, `GET /api/projects/{pid}/graph/entities/{eid}/neighborhood?depth=`; `create_app(..., graphs: ProjectGraphs | None = None)`.

Wire shapes:
```json
{"entities": [{"entity_id": "…", "name": "…", "entity_type": "Person"}], "next_after": null}
{"root": {…}, "entities": [{…}], "relationships": [{"source_id": "…", "target_id": "…", "relationship_type": "advised"}]}
```

`depth` above `MAX_NEIGHBORHOOD_DEPTH` is a **422**, not a silent clamp — a caller asking for depth 5 has misunderstood, and quietly giving them depth 2 hides that. (The port still clamps as defence in depth; the two are not redundant, they serve different callers.)

- [ ] **Step 1: Write the failing route tests** including `test_asking_past_the_depth_cap_is_refused` asserting 422
- [ ] **Step 2–5: verify failure, implement, verify pass, commit**

---

# Slice 5 — The graph pane

### Task 12: `expand` — the merge fold

**Files:**
- Create: `frontend/src/domain/knowledge/graph.ts` + `graph.test.ts`

**Interfaces:**
- Produces:
  ```typescript
  export interface GraphNode { readonly id: string; readonly name: string; readonly entityType: string }
  export interface GraphLink { readonly source: string; readonly target: string; readonly relationshipType: string }
  export interface GraphView {
    readonly nodes: readonly GraphNode[]
    readonly links: readonly GraphLink[]
    readonly expanded: ReadonlySet<string>
  }
  export const emptyGraph: GraphView
  export const expand: (view: GraphView, hood: Neighborhood) => GraphView
  export const isExpanded: (view: GraphView, id: string) => boolean
  ```

This is the one with real subtlety, and it gets the treatment `applyNote` got in `domain/knowledge/extraction.ts` — read that file first.

**Node object identity must be preserved.** `react-force-graph-2d` mutates node objects in place to store `x`/`y`. If `expand` returns fresh objects for nodes already present, every existing node loses its position and the whole graph re-simulates from scratch on each expansion. So: merge by id, and for an id already in `view.nodes`, keep **the existing object reference**.

- [ ] **Step 1: Write the failing tests**

```typescript
it('keeps the existing node object so d3 does not lose its position', () => {
  // react-force-graph writes x/y onto the node objects themselves. A fresh
  // object for a node already on screen throws its position away and the
  // whole graph jumps on every expansion.
  const first = expand(emptyGraph, hoodWith('prandtl'))
  const second = expand(first, hoodWith('prandtl', 'karman'))

  expect(second.nodes.find((n) => n.id === 'prandtl')).toBe(
    first.nodes.find((n) => n.id === 'prandtl'),
  )
})

it('does not duplicate a node arriving from two neighborhoods', () => {
  const view = expand(expand(emptyGraph, hoodWith('a', 'shared')), hoodWith('b', 'shared'))

  expect(view.nodes.filter((n) => n.id === 'shared')).toHaveLength(1)
})

it('does not duplicate an edge seen from both of its ends', () => {
  const view = expand(expand(emptyGraph, edge('a', 'b')), edge('b', 'a'))

  expect(view.links).toHaveLength(1)
})

it('records what has been expanded so a node is not re-fetched', () => {
  const view = expand(emptyGraph, hoodWith('prandtl'))

  expect(isExpanded(view, 'prandtl')).toBe(true)
})
```

The edge-dedup test needs a stable edge key independent of direction only when `relationshipType` matches; `advised(a→b)` and `advised(b→a)` are genuinely different edges, so key on `source|target|type` and let the test above pass by having `edge('b','a')` be the *same* direction arriving twice. Write the test to match the semantics you implement, and say which you chose in a comment.

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run to verify pass**
- [ ] **Step 5: Commit**

---

### Task 13: `GraphCanvas` and `GraphPane`

**Files:**
- Create: `frontend/src/presentation/research/GraphCanvas.tsx`, `GraphPane.tsx` + `GraphPane.test.tsx`
- Create: `frontend/src/application/research/graph-store.ts` + `.test.ts`
- Create: `frontend/src/infrastructure/http/graph-repository.ts`
- Modify: `dto.ts`, `mappers.ts`, `ports/repositories.ts`, `container.ts`, `keys.ts`, `ResearchView.tsx`, `research.css`

**Interfaces:**
- Consumes: `expand`/`emptyGraph` (Task 12); routes from Task 11; `application/knowledge/extraction-store.ts` as the zustand store template.
- Produces: `createGraphStore({ graphs, projectId })` with `search(term)`, `expandNode(id)`, `view: GraphView`.

`GraphCanvas` is the only module importing `react-force-graph-2d`, and `GraphPane` loads it with `React.lazy` so the console does not pay 62 kB to render a session transcript.

**Test the pane, mock the canvas.** `vi.mock('./GraphCanvas.tsx')` — asserting on canvas pixels tests the library, not our code. The pane's tests assert: a search populates the store, clicking a result expands it, and an already-expanded node is not re-fetched.

- [ ] **Step 1: Write the failing `graph-store.test.ts`**
- [ ] **Step 2–4: verify failure, implement, verify pass**
- [ ] **Step 5: Write the failing `GraphPane.test.tsx` with `GraphCanvas` mocked**
- [ ] **Step 6–8: verify failure, implement both components, verify pass**
- [ ] **Step 9: Commit** (dependency and budget land in Task 14, so this commit must not add the dep — write `GraphCanvas` against the import and let the build fail until Task 14, or do Task 14 first if that ordering is cleaner; say which you chose in the commit message)

---

### Task 14: The dependency and the budget

**Files:**
- Modify: `frontend/package.json`, `vite.config.ts`, `scripts/check-size.mjs`

- [ ] **Step 1: `npm install react-force-graph-2d@^1.29.1`**
- [ ] **Step 2: Add a `graph-` entry to `manualChunks` in `vite.config.ts`** so it is its own chunk and never merges into `vendor-`
- [ ] **Step 3: `npm run build`, then `node scripts/check-size.mjs`** — expect it to FAIL, naming the chunk over budget. That failure is the gate doing its job; read it and record the real number.
- [ ] **Step 4: Raise the budget to the measured number**, `graph-: 62` and `total: 242` (adjust to what step 3 actually measured — do not copy these numbers blind)
- [ ] **Step 5: `npm run verify`** → PASS
- [ ] **Step 6: Commit**

```bash
git commit -m "build: buy a force-directed graph, and say what it cost

react-force-graph-2d is 62 kB gzipped, in its own chunk and lazily loaded,
so the console pays for it only on the research page. Canvas rather than
WebGL, and a real React component rather than an imperative adapter we
would own -- the React bindings for cytoscape and vis-network are both
years unmaintained.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

# Slice 6 — Seeding

### Task 15: `TopicSeeder`

**Files:**
- Create: `research_team/application/topic_seeding.py`, `tests/application/test_topic_seeding.py`

**Interfaces:**
- Consumes: `TurnSupervisor` (see how `auto_research.py` drives one turn); `SessionService.start_in_project` / `attach_project` / `release_project` as used at `app.py:598`.
- Produces: `TopicSeeder.seed(project_id, subject, max_topics) -> SeedingRun`; `SEEDING_PROMPT`.

**One turn, not a run.** `auto_research.py` argues for round-per-turn because investigation is long and failure-prone; seeding is one bounded burst of naming, and a failure loses seconds. Put that reasoning in the module docstring.

`SEEDING_PROMPT` states the rule as a decision procedure:

> Open a set of broad, orthogonal topics covering this subject. Work from your own knowledge. Call `web_search` **only** if you cannot confidently name a varied set for this subject — if the subject is unfamiliar, or if the topics you can name all cluster in one corner of it.

Written as "if you cannot", not "if search is available", so the prompt reads identically whether or not `AGENT_SEARXNG_URL` is set. With no search configured the tool is not registered and the agent proceeds from knowledge, which is the preferred path anyway.

- [ ] **Step 1: Write the failing tests** with a fake model that emits `open_topic` calls

```python
async def test_seeding_opens_the_topics_the_model_named(seeder, fake_model):
    fake_model.will_call("open_topic", question="How does spacing affect retention?", rationale="core")

    await seeder.seed(project_id, "spaced repetition", max_topics=8)

    assert [t.question for t in await topic_reader.list_topics()] == [
        "How does spacing affect retention?"
    ]


async def test_seeding_releases_the_project_even_when_the_turn_fails(seeder, failing_model):
    """A seeding run that died holding the project would lock out every later
    one, and the failure is seconds old with nothing to show for it."""
    with pytest.raises(Exception):
        await seeder.seed(project_id, "anything", max_topics=8)

    state = await service.project_state(project_id)
    assert state.active_session_id is None
```

- [ ] **Step 2–4: verify failure, implement, verify pass**
- [ ] **Step 5: Commit**

---

### Task 16: The seed route and `SeedingActivity`

**Files:**
- Create: `research_team/interfaces/web/seeding.py`
- Modify: `app.py`, `presenters.py`, `web.py`
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: `ExtractionActivity` in `research_team/interfaces/web/extraction.py` — copy its shape exactly.
- Produces: `POST /api/projects/{pid}/topics/seed` → 202; `GET /api/projects/{pid}/topics/seed` → catch-up.

Seeding's lifecycle is provisional state on the same footing as extraction frames: per-project, in-memory, with a catch-up route because unpositioned SSE frames cannot replay through `Last-Event-ID`. The opened topics themselves need no new channel — `open_topic` already appends to the log, and the page invalidates `queryKeys.topics(projectId)` on those frames.

- [ ] **Step 1: Write the failing route tests** — 202 with a run body; a second concurrent seed is 409
- [ ] **Step 2–5: verify failure, implement, verify pass, commit**

---

### Task 17: `SeedPanel`

**Files:**
- Create: `frontend/src/presentation/research/SeedPanel.tsx` + `.test.tsx`
- Modify: `topic-repository.ts`, `ports/repositories.ts`, `ResearchView.tsx`, `research.css`

- [ ] **Step 1: Write the failing test** — submitting a subject calls seed; the button is disabled while a run is active; topics appearing in the list during a run
- [ ] **Step 2–5: verify failure, implement, verify pass, commit**

---

### Task 18: Cross-links, build, and the full gate

**Files:**
- Modify: `frontend/src/presentation/course/CourseView.tsx`, `frontend/src/presentation/shell/Breadcrumbs.tsx`, `research_team/interfaces/web/static/**` (build output)

- [ ] **Step 1: Add a link from the course page to the research page and back**, and a breadcrumb entry
- [ ] **Step 2: `npm run verify`** → PASS
- [ ] **Step 3: `npm run build`** and commit the built output — `web.py` serves it with no Node toolchain, so an uncommitted build means the feature does not exist for anyone running the server
- [ ] **Step 4: `uv run pytest -q`** → expect ≥1590 passing, 0 failures
- [ ] **Step 5: Commit the build separately**, following the `build:` commits in the log

---

## Self-Review

**Spec coverage.** Part A read → Tasks 1–5. Part A management → Tasks 6–7. Part B seeding → Tasks 15–17. Part C documents → Task 8. Part D graph → Tasks 9–14. Frontend/routing → Tasks 4, 18. Testing constraints → embedded in every task.

**One gap found and closed:** the spec assumed a readable graph store existed. It does not outside attachment, and a second one would go stale. Task 9 (`ProjectGraphs`) was added to give the store one owner. This is the only structural addition beyond the spec, and it is a prerequisite for Part D rather than a change to it.

**One spec inaccuracy found and corrected:** the spec said documents need "almost nothing to build", but `list_documents` filters dropped documents out and `source_view` omits `dropped_reason`, so the spec's own requirement that dropped documents stay visible needs a backend change. Folded into Task 8.

**Ordering note:** Tasks 13 and 14 have a circular smell — the pane needs the dependency, the budget commit wants a built pane. Task 13 Step 9 names the choice explicitly rather than leaving it ambiguous.
