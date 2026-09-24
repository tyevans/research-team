# Bounded Context Architecture & Wiring Guide

A comprehensive architectural specification for the bounded contexts under `research_team`: context boundaries, ownership invariants, ideal integration patterns, and the roadmap for resolving cross-BC coupling.

---

## 1. Architectural Vision & Context Map

`research_team` is an **event-sourced, Domain-Driven Design (DDD)** system implementing **Hexagonal Architecture (Ports & Adapters)**. The codebase is divided into seven domain-specific Bounded Contexts (BCs), supported by a shared platform foundation, pluggable infrastructure adapters, driving interfaces, and a composition root.

```
+-----------------------------------------------------------------------------------+
|                                INTERFACES (Driving)                               |
|                  +--------------------+     +-------------------+                 |
|                  |     Web (FastAPI)  |     |     CLI (REPL)    |                 |
|                  +---------+----------+     +---------+---------+                 |
+----------------------------|--------------------------|---------------------------+
                             |                          |
+----------------------------v--------------------------v---------------------------+
|                              WIRING (Composition Root)                            |
|             Assembles ApplicationState, Injects Adapters, Runs Lifecycles         |
+------------------------------------+----------------------------------------------+
                                     |
+------------------------------------v----------------------------------------------+
|                             BOUNDED CONTEXTS (Domain Core)                        |
|                                                                                   |
|  +--------------------+  +--------------------+  +-----------------------------+  |
|  |     Tenancy        |  |     Session        |  |          Research           |  |
|  | - Tenant aggregate |  | - Session agg.     |  | - Topic aggregate           |  |
|  | - Project agg.     |  | - Turn execution   |  | - Corpus aggregate          |  |
|  | - Authorization    |  | - Approval gates   |  | - MediaProposals agg.       |  |
|  | - User identity    |  | - Context strategy |  | - ResearchRun aggregate     |  |
|  +--------------------+  +--------------------+  +-----------------------------+  |
|                                                                                   |
|  +--------------------+  +--------------------+  +-----------------------------+  |
|  |    Knowledge       |  |    Curriculum      |  |          Dialogue           |  |
|  | - Discovered       |  | - Course agg.      |  | - AskConversation agg.      |  |
|  |   Ontologies       |  | - AuthoringRun     |  | - SocraticDialogue agg.     |  |
|  | - Entity Judgements|  | - Learning Areas   |  | - Component Projections     |  |
|  | - Graph Projections|  | - LearnerProgress  |  +-----------------------------+  |
|  +--------------------+  +--------------------+                                   |
|                                                                                   |
|                          +--------------------+                                   |
|                          |      Settings      |                                   |
|                          | - Model Profiles   |                                   |
|                          | - Provider Specs   |                                   |
|                          +--------------------+                                   |
+-----------------------------------------------------------------------------------+
                                     |
+------------------------------------v----------------------------------------------+
|                         PLATFORM (Shared Technical Foundation)                    |
|          LiveFeed, Locators, Frontmatter, Text, Retry, Interactive Components     |
|          (Zero knowledge of domain aggregates, sessions, or use cases)            |
+-----------------------------------------------------------------------------------+
                                     ^
                                     |
+------------------------------------+----------------------------------------------+
|                       INFRASTRUCTURE (Driven / Secondary Adapters)                 |
|       SQLite EventStore, Neo4j Graph, PGVector, DeepAgent LLM, SearXNG Tools      |
+-----------------------------------------------------------------------------------+
```

---

## 2. Bounded Context Catalog & Boundaries

Each Bounded Context owns its own **Ubiquitous Language**, **Domain Invariants**, **Event Streams**, and **Application Services**. A context must never violate another context's boundary.

### 2.1 Tenancy (`research_team/tenancy`)
* **Core Aggregates**: `Tenant`, `Project`, `User`.
* **Ubiquitous Language**: Tenant, Project, Principal, Grant, Role, Membership, Tip Catch-up.
* **Responsibilities**:
  - Managing multi-tenant isolation and user organizations.
  - Project workspace lifecycle: creating, archiving, deleting projects, tracking the active project tip stream.
  - Role-based authorization (`Authorizer`, `RoleTableAuthorizer`, `PermissiveAuthorizer`).
  - Pre-authorized fetch grants (`FetchGrant`, `GrantRegistry`).
* **Boundary Rules**: Tenancy owns *who* is acting and *which workspace* they own. It does **not** execute agent turns or render chat messages.

### 2.2 Session (`research_team/session`)
* **Core Aggregates**: `Session`.
* **Ubiquitous Language**: Turn, Approval, Tool Call, Fork, Autonomy Policy, Context Strategy, Compaction, Activity Stream.
* **Responsibilities**:
  - Event-sourced turn execution and atomicity (a turn commits all-or-nothing).
  - Human-in-the-loop (HITL) approval gates and autonomy level enforcement (`AutonomyPolicy`).
  - Session history folding, state reconstruction, and message compaction (`PreparedContext`).
  - Read-model projections for session lists and statistics (`SessionSummaries`, `SessionQueries`).
* **Boundary Rules**: Session owns *agent execution state and conversation log*. It does **not** own project organizational rules or curriculum progress.

### 2.3 Research (`research_team/research`)
* **Core Aggregates**: `Topic`, `Corpus`, `MediaProposals`, `ResearchRun`.
* **Ubiquitous Language**: Topic, Dispatch, Research Round, Supervisor, Source Document, Media Proposal, Perception, Citation.
* **Responsibilities**:
  - Autonomous research exploration across a topic queue.
  - Source document ingestion, content hashing, media perception, and attribution.
  - Multi-round topic supervision and budget management.
* **Boundary Rules**: Research owns *evidence gathering and source corpus*. It does **not** define curriculum or perform knowledge graph entity resolution.

### 2.4 Knowledge (`research_team/knowledge`)
* **Core Aggregates**: None (relies on read projections and external graph models, plus domain records like `EntityJudgement`).
* **Ubiquitous Language**: Entity, Discovered Class, Ontology, Knowledge Graph, Coordinate Translation, Chunking, Consolidation, Redstring.
* **Responsibilities**:
  - Discovered ontology extraction from text sources (`OntologyDiscoveryService`).
  - Entity definition cache, usages, and resolution judgements (`DefinitionService`).
  - Graph projection queries (`GraphReadPort`, `ProjectGraphs`).
* **Boundary Rules**: Knowledge owns *structured knowledge representation and entity semantics*. It does **not** ingest raw web searches or manage agent workflows.

### 2.5 Curriculum (`research_team/curriculum`)
* **Core Aggregates**: `Course`, `CourseAuthoringRun`, `LearnerProgress`.
* **Ubiquitous Language**: Course, Unit, Lesson, Learning Area, Learning Path, Backward Design (UbD), Rubric, Learner Attempt, Checklist.
* **Responsibilities**:
  - Hierarchical course structures, realization, and catalog browsing (`CourseService`, `CatalogService`).
  - Pedagogical authoring via subagents (`CourseAuthor`).
  - Learner evaluation, score tracking, and checklist completion (`LearnerProgressService`).
* **Boundary Rules**: Curriculum owns *learning structures and learner progress*. It does **not** run raw REPL sessions or host knowledge graph databases.

### 2.6 Dialogue (`research_team/dialogue`)
* **Core Aggregates**: `AskConversation`, `SocraticDialogue`.
* **Ubiquitous Language**: Ask, Socratic Turn, Dialogue Goal, Stopping Condition, Interactive Component View, Dialogue Frame.
* **Responsibilities**:
  - Ephemeral user queries over gathered material (`AskService`).
  - Resumable, goal-directed educational dialogues (`SocraticDialogueService`).
  - Projecting component interactions (`ComponentProjection`).
* **Boundary Rules**: Dialogue owns *educational conversation flows and live questioning*.

### 2.7 Settings (`research_team/settings`)
* **Core Aggregates**: `SettingsRevision` / Configuration Spec.
* **Ubiquitous Language**: Model Profile, Provider Spec, Secret, Probe, Effective Settings.
* **Responsibilities**:
  - Managing model profiles (e.g. Anthropic, OpenAI, local Ollama) and provider credentials.
  - Validating configuration overlays and health probing.
* **Boundary Rules**: Settings owns *environmental configuration and AI credentials*.

---

## 3. Ideal Wiring & Cross-BC Communication Patterns

To maintain high cohesion and low coupling across BCs, all cross-context interactions must follow one of the following **four canonical patterns**:

```
+-----------------------------------------------------------------------------------+
|                        PATTERN A: Composition Root Assembly                       |
|   wiring/ builds BC services independently and injects them into ApplicationState |
+-----------------------------------------------------------------------------------+

+-----------------------------------------------------------------------------------+
|                        PATTERN B: Event-Driven Choreography                       |
|   BC A appends DomainEvent  --->  EventStore  --->  BC B Projection consumes      |
+-----------------------------------------------------------------------------------+

+-----------------------------------------------------------------------------------+
|                        PATTERN C: Inbound Port & Adapter (ACL)                    |
|   BC A declares Protocol Port  <---  wiring/ passes BC B Adapter (translates)     |
+-----------------------------------------------------------------------------------+

+-----------------------------------------------------------------------------------+
|                        PATTERN D: Pure Platform Foundations                       |
|   platform/ shared utilities have ZERO dependencies on Domain/App layers          |
+-----------------------------------------------------------------------------------+
```

### Pattern A: Composition Root (`research_team/wiring`)
* Cross-BC workflows must be composed in `research_team/wiring/`.
* No domain Bounded Context should ever import another Bounded Context's application service to "drive" a workflow.
* `ApplicationState` acts as the single typed container holding all instantiated services, runners, and repositories.
* Callers in `interfaces/web` or `interfaces/cli` receive `ApplicationState` (via dependency injection) and access the appropriate BC service directly.

### Pattern B: Event-Driven Integration (Event Sourcing Pub/Sub)
* When an action in BC A has ramifications in BC B, BC A appends a domain event to the event store.
* BC B registers an asynchronous projection runner or subscriber (`eventsource` event feed).
* **Example**: When `CorpusEditor` in `research` records `DocumentStored`, the event stream notifies `OntologyRunner` or `ExtractionChannel` without `research` needing direct coupling to `knowledge` or `session`.

### Pattern C: Consumer-Defined Ports & Anti-Corruption Layers (ACL)
* If BC A requires data from BC B synchronously:
  1. BC A declares a **Protocol (Port)** in its own package (e.g., `curriculum/application/ports.py` defines `KnowledgeQueryPort`).
  2. The port speaks **only the language of BC A**.
  3. `wiring/` supplies an adapter that delegates to BC B and translates types (Anti-Corruption Layer).
* **Rule**: Never import domain entities or internal service implementations across BC boundaries.

### Pattern D: Dependency Inversion for Shared Platform (`platform`)
* The `platform/` package is a horizontal utility foundation:
  - Markdown component definitions & validators (`platform/components`)
  - Shared algorithms (`locators`, `frontmatter`, `retry`, `slugify`)
  - Generic event streaming primitives (`live_feed`)
* **Strict Invariant**: `platform` must have **zero imports** from `research_team.session`, `research_team.research`, `research_team.tenancy`, or any other domain context. Any ports or context strategies currently residing in `platform/shared/` must be moved to their respective BCs.

---

## 4. Current Cross-BC Violations & Diagnostic Matrix

A complete audit of `research_team` revealed the following specific architectural violations:

| # | Source Module | Target Module | Nature of Violation | Refactoring Resolution |
| :--- | :--- | :--- | :--- | :--- |
| **V1** | `platform/shared/ports.py` | `session.domain`, `session.application.summaries`, `research.application.corpus_read` | **Platform Inversion**: Foundational shared layer imports domain aggregates (`Session`) and use cases. Contains a runtime `__getattr__` dynamic import hack for `CorpusReadPort`. | Move `SessionRepository`, `SessionSummaries`, `TurnExecutor` into `session/application/ports.py`. Remove `CorpusReadPort` dynamic hack. Re-export in `platform/shared/ports.py` for backward compatibility. |
| **V2** | `platform/shared/context.py` | `session.domain` (`SessionState`) | **Platform Inversion**: Context management (`PreparedContext`, `ContextStrategy`, `Compaction`, `FullHistory`) is purely a Session runtime strategy, not a platform utility. | Move `context.py` to `session/application/context.py` (or re-export with deprecation). `platform` must not know about `SessionState`. |
| **V3** | `session/application/session_service.py` | `curriculum`, `tenancy`, `knowledge` | **God-Facade Anti-Pattern**: `SessionService` exposes `learner_progress()`, `record_attempt()`, `list_projects()`, `project_state()`, `delete_project()`, and holds references to `ProjectGraphs`. | Deprecate pass-through methods on `SessionService`. Web and CLI routes access `app_state.projects` (`ProjectSessions`), `app_state.learner_progress`, and `app_state.graphs` directly. |
| **V4** | `tenancy/application/project_binding.py` & `project_sessions.py` | `session.domain`, `platform.shared.ports` | **Bidirectional / Cyclic Entanglement**: `tenancy` imports `SessionPurpose`, `FILE_EVENT_TYPES`, `SessionRepository`, while `session/application/turn_runner.py` imports `project_context` from `tenancy`. | Define an explicit `ProjectBindingPort` in `session`. Coordinate session-in-project binding in `wiring` or decoupling via port interfaces. |
| **V5** | `dialogue/application/socratic.py` | `curriculum/application/learner_progress`, `curriculum/domain` | **Direct Domain Cross-Coupling**: `SocraticDialogueService` directly imports `LearnerProgressService` and `LearnerProgress` aggregate. | Dialogue should define a `DialogueProgressPort` (Protocol), with an adapter provided at composition time in `wiring/dialogue_wiring.py`. |
| **V6** | `curriculum/application/area_graph.py`, `area_projection.py`, `curriculum.py` | `knowledge/application/graph_read` | **Cross-Context Domain Leakage**: Curriculum directly depends on `knowledge.application.graph_read` types (`Graph`, `GraphReadPort`, `GraphRelationship`). | Curriculum should define its own `CurriculumGraphPort` in `curriculum/application/ports.py`, satisfied by `ProjectGraphs` / `GraphReader` via `wiring`. |
| **V7** | `research/application/corpus_writer.py`, `corpus_editing.py`, `perception.py` | `knowledge/application/knowledge` | **Shared Domain Limits Misplaced**: `MAX_DOCUMENT_CHARS` and `SourceRef` are imported from `knowledge` into `research`. | Move shared document size limits and source references to a shared domain contract or platform constants module. |
| **V8** | `research/application/topic_dispatch.py`, `topic_seeding.py` | `session/application/session_service` | **Direct Use-Case Coupling**: Research dispatch and seeding instantiate/invoke `SessionService` directly. | Decouple research dispatch to depend on a generic `AgentSessionLauncherPort` (Protocol) fulfilled by `wiring`. |

---

## 5. Phased Refactoring Roadmap

To resolve these cross-BC concerns safely without regressions, changes are partitioned into five discrete, self-verifying phases:

```
[Phase 1: Invert Foundation]  ===>  [Phase 2: Untangle Ports]  ===>  [Phase 3: Clean God-Facade]
Clean platform/shared/ports.py      Migrate ContextStrategy to       Route callers to dedicated
Eliminate upward imports            session/application/context      services on ApplicationState
             |                                                                     |
             v                                                                     v
[Phase 4: ACL Protocols for Domain Cross-Reads]  ===>  [Phase 5: Architecture Enforcement Test]
Define Ports in dialogue, curriculum, research         Add cross-BC import boundary checks in
Inject adapters in wiring/                             tests/test_architecture.py
```

### Phase 1: Clean Foundation (`platform/shared`)
1. Remove `from research_team.session.domain import Session` from `platform/shared/ports.py`.
2. Move `SessionRepository`, `SessionSummaries`, `SummaryHealth`, `TurnExecutor`, `ActivityReporter` definitions to `session/application/ports.py`.
3. In `platform/shared/ports.py`, re-export them from `session/application/ports.py` to maintain 100% backward compatibility for existing external callers.
4. Remove the `__getattr__` dynamic import hack for `CorpusReadPort` from `platform/shared/ports.py`. Update `knowledge/application/ontology_discovery.py` and `entity_definitions.py` to import `CorpusReadPort` from `research.application.corpus_read`.

### Phase 2: Decouple Session Context Management
1. Move `platform/shared/context.py` logic into `session/application/context.py`.
2. Re-export `ContextStrategy`, `FullHistory`, `PreparedContext`, etc., from `platform/shared/context.py` with a deprecation notice.
3. Update imports in `session/application/turn_runner.py` and `infrastructure/agent/compaction.py`.

### Phase 3: Decouple `SessionService` God-Facade
1. In `research_team/wiring/application_state.py`, ensure `ApplicationState` exposes:
   - `projects: ProjectSessions`
   - `learner_progress: LearnerProgressService`
2. Update web routers (`interfaces/web/app_readers.py`, `interfaces/web/projects.py`, `interfaces/web/curriculum.py`) to access `app_state.projects` and `app_state.learner_progress` directly rather than traversing `service._project_sessions` or `service._learner_progress`.
3. Keep the delegate methods on `SessionService` with backward-compatibility docstrings so existing integration tests continue to run smoothly.

### Phase 4: Establish Anti-Corruption Layers (ACL) for Domain Interactions
1. **Dialogue -> Curriculum**:
   - Define `ProgressTrackerPort` in `dialogue/application/ports.py`.
   - In `wiring/dialogue_wiring.py`, provide the adapter wrapping `LearnerProgressService`.
2. **Curriculum -> Knowledge**:
   - Define `CurriculumGraphPort` in `curriculum/application/ports.py`.
   - Satisfy it using `ProjectGraphs` during catalog wiring in `wiring/catalog_wiring.py`.
3. **Research -> Session**:
   - Define `SessionLauncherPort` in `research/application/ports.py`.
   - In `wiring/service_wiring.py`, inject the callable creating research sessions.

### Phase 5: Architecture Enforcement Gates
1. Update `tests/test_architecture.py` to include:
   - `test_platform_has_no_domain_dependencies`: Verifies that `platform` imports nothing from `research_team.{bc}`.
   - `test_bounded_context_isolation`: Verifies that no domain BC imports domain aggregates or entities from another domain BC.
   - All cross-context calls must pass through `wiring/` or declared Protocols.
