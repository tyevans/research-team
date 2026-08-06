# deepagents: current API, this repo's integration, and options for staged instructional-design workflows

**Accurate as of `deepagents==0.7.1`** (installed in `/home/ty/workspace/research-team/.venv`), against
`langchain==1.3.14`, `langchain-core==1.5.3`, `langgraph==1.2.10`, `langgraph-prebuilt==1.1.0`.

Everything marked "verified" was read out of the installed package source or this repo's own source. Claims
sourced only from published documentation are attributed. Anything I could not confirm is marked
**UNVERIFIED**.

Sources:

- Installed source: `.venv/lib/python3.13/site-packages/deepagents/` (0.7.1)
- <https://docs.langchain.com/oss/python/deepagents/overview> (package `Homepage` in METADATA)
- <https://reference.langchain.com/python/deepagents/> (package `Documentation`)
- <https://github.com/langchain-ai/deepagents>
- Doc pages cited inline: `/customization`, `/context-engineering`, `/models`, `/backends`,
  `/permissions`, `/human-in-the-loop`, `/streaming`, `/skills` under
  `https://docs.langchain.com/oss/python/deepagents/`

---

## 1. How this repo already uses deepagents

### 1.1 Where it lives

deepagents is confined to `research_team/infrastructure/agent/` plus the composition root. The application
layer names no framework — `tests/test_architecture.py` enforces that.

| File | Role |
| --- | --- |
| `research_team/infrastructure/agent/deep_agent.py` | `DeepAgentTurnExecutor` — the only caller of `create_deep_agent` |
| `research_team/infrastructure/agent/backend.py` | `EventSourcedBackend(StateBackend)` — the agent's filesystem *is* the event-sourced aggregate |
| `research_team/infrastructure/agent/approval.py` | maps `AutonomyPolicy` onto langchain's `InterruptOnConfig` |
| `research_team/infrastructure/agent/delegation.py` | the single `worker` subagent spec + its prompt fragment |
| `research_team/infrastructure/agent/knowledge_tools.py` | `remember` / `graph_search` / `unmerge` over redstring |
| `research_team/infrastructure/agent/search.py` | SearXNG tool, registered only when configured |
| `research_team/infrastructure/agent/compaction.py` | `SummarizingStrategy` — a *repo-side* context strategy, not deepagents middleware |
| `research_team/composition.py` | picks model, tools, subagents, prompt suffixes, policy |

### 1.2 Agent construction

`DeepAgentTurnExecutor._invoke` (`research_team/infrastructure/agent/deep_agent.py`) builds a **fresh agent
on every turn**:

```python
agent = create_deep_agent(
    model=self._model,
    tools=self._tools or None,
    backend=EventSourcedBackend(session),
    system_prompt=system_prompt,
    interrupt_on=interrupt_config(self._policy),
    checkpointer=MemorySaver(),
    subagents=self._subagents or None,
)
```

Notable properties of the current integration:

- **No `middleware=` is passed at all.** The repo uses none of deepagents' or langchain's middleware
  extension points today. That is the single most important fact for the workflow question below — the
  middleware slot is entirely free.
- **No `state_schema=`, no `store=`, no `context_schema=`, no `skills=`, no `memory=`, no `permissions=`,
  no `response_format=`.**
- The checkpointer is `MemorySaver()`, created per turn, and the `thread_id` is
  `f"{session.aggregate_id}:{session.state.turn_index}"`. It exists *only* so `Command(resume=...)` has
  somewhere to park a halted graph. **Durability is the event log, not the checkpointer.** Any workflow
  design that wants state to survive a process restart must put it in the aggregate, not in LangGraph
  state.
- The model is `ChatOpenAI` pointed at a local OpenAI-compatible endpoint (`build_model()`), `temperature=0`.

### 1.3 Backend

`EventSourcedBackend` subclasses `deepagents.backends.state.StateBackend` and overrides exactly two private
seams — `_read_files()` and `_send_files_update()` — plus `edit()` for intent capture. Every file write,
edit, and delete becomes a domain event (`WriteFile` / `EditFile` / `DeleteFile`) on the `CodingSession`
aggregate *as it happens*, before the turn commits. Subagents share this backend instance, so delegated
writes land on the same stream.

This is the persistence seam any staged workflow should reuse: **a stage artifact written to a file path is
already durable, auditable, and replayable.**

### 1.4 Tools and subagents

- Tools are assembled in `composition.py`: the SearXNG search tool (only if `SEARXNG_URL` is set) and, when
  a project is attached, the three knowledge-graph tools. `KnowledgeAttachment` swaps the executor's tool
  list between turns via `executor.set_tools(...)` — safe because the agent is rebuilt each turn.
- Subagents: a single declarative `SubAgent`-shaped dict, `WORKER`, enabled only in `context_mode="delegate"`
  (`_context_parts` in `composition.py`). It has no `tools` override, so it inherits the main agent's tools.
- Prompt composition is string concatenation in the composition root:
  `DEFAULT_SYSTEM_PROMPT + DELEGATION_PROMPT + SEARCH_PROMPT + KNOWLEDGE_PROMPT`. There is no dynamic
  per-step prompt mechanism today.

### 1.5 Interrupts / human-in-the-loop

`interrupt_config(policy)` produces one `InterruptOnConfig` per gated tool with a `when` predicate closing
over the live `AutonomyPolicy`, so autonomy changes mid-session take effect on the next tool call.
`allowed_decisions = ["approve", "edit", "reject"]` — deliberately no `respond`, because inventing a tool
result would falsify the log.

The resume loop in `_invoke` reads `state["__interrupt__"]`, walks `value["action_requests"]` paired
positionally with `value["review_configs"]`, records a `RecordToolDecision` event for each, and resumes with
`Command(resume={"decisions": [...]})`. Order and count are load-bearing.

### 1.6 Streaming

One `agent.astream(..., stream_mode=["values", "messages"])` pass feeds two channels:

- `values` chunks → full state; new messages are converted by `to_activity_message` and reported.
- `messages` chunks → token deltas, filtered by `metadata["langgraph_node"] == "model"` (the constant
  `MAIN_AGENT_NODE`) so subagent tokens don't render as the main agent's answer.

Notes are handed to an `ActivityReporter`, which the web layer (`interfaces/web/app.py`, `TurnActivity`)
fans out over SSE at `/api/stream`. Reporter exceptions are swallowed and logged — the side channel can
never fail the turn.

Note that `subgraphs=True` is **not** passed. The published streaming doc uses `subgraphs=True` plus the
`ns` namespace list to attribute subagent output; this repo instead discriminates on `langgraph_node`. Any
design that wants to *show* per-stage subagent progress in the UI will likely need `subgraphs=True` and a
richer attribution scheme than the current binary main/not-main test.

---

## 2. The library itself (0.7.1)

### 2.1 `create_deep_agent`

Verified signature from `deepagents/graph.py`:

```python
def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware[StateT_co, ContextT]] = (),
    subagents: Sequence[SubAgent | CompiledSubAgent | AsyncSubAgent] | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    permissions: list[FilesystemPermission] | None = None,
    backend: BackendProtocol | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    response_format: ResponseFormat[ResponseT] | type[ResponseT] | dict[str, Any] | None = None,
    state_schema: type[DeepAgentState] | None = None,
    context_schema: type[ContextT] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
) -> CompiledStateGraph[...]
```

**`async_create_deep_agent` does not exist in 0.7.1.** `grep -rn "async_create_deep_agent"` over the
installed package returns nothing, and it is not in `deepagents.__all__`. The single `create_deep_agent`
returns a `CompiledStateGraph` that supports both `.invoke`/`.stream` and `.ainvoke`/`.astream`; the repo
already uses `astream`. If a spec references `async_create_deep_agent`, it is referring to an older or
JS-side API. Treat the name as **removed/nonexistent**.

Other verified details:

- `model=None` is **deprecated since 0.5.3** and will be removed in 1.0.0. Always pass a model. The repo
  already does.
- `system_prompt` is assembled as `USER -> BASE -> SUFFIX`, where `BASE`/`SUFFIX` come from the active
  *harness profile* (see 2.6). With no profile content, the model gets only your string. Passing a
  `SystemMessage` preserves `cache_control` blocks for Anthropic prompt-cache breakpoints.
- `tools=` is strictly **additive** — it can never remove a built-in. Removing a built-in requires
  registering a `HarnessProfile` with `excluded_tools`.
- `state_schema` must subclass `DeepAgentState` (so the `DeltaChannel` reducer on `messages` survives). The
  docstring explicitly recommends preferring middleware-contributed state over a custom `state_schema`.
  When provided, it *is* forwarded to declarative `SubAgent` compilation, so subagents see the same fields;
  `CompiledSubAgent` runnables do not inherit it.

### 2.2 Built-in tools

Default tool suite (from the `create_deep_agent` docstring): `ls`, `read_file`, `write_file`, `edit_file`,
`glob`, `grep`, `execute`, and `task`.

- `execute` only works if the backend implements `SandboxBackendProtocol`; otherwise it returns an error
  string. `EventSourcedBackend` does not, which is what `tests/integration/test_no_shell.py` pins.
- `task` is the subagent-spawning tool. It is **not exposed** if there are no synchronous subagents — i.e.
  none passed *and* the default general-purpose subagent disabled via
  `GeneralPurposeSubagentProfile(enabled=False)` on the harness profile.

**There is no planning/todo tool in the default deepagents stack in 0.7.1.** This contradicts the widely
repeated "deepagents = planning tool + filesystem + subagents + prompt" framing. `write_todos` comes from
`langchain.agents.middleware.TodoListMiddleware`, and in 0.7.1 the only place deepagents installs it is the
OpenAI Codex harness profile (`deepagents/profiles/harness/_openai_codex.py`). To get a todo list on the
local-model setup this repo runs, you must pass `TodoListMiddleware()` yourself in `middleware=`.

### 2.3 Backends

`deepagents.backends` exports: `StateBackend` (default; files in graph state), `FilesystemBackend` (real
disk, rooted at `root_dir`), `StoreBackend` (LangGraph `BaseStore`, persists across threads;
namespace-scoped via a `NamespaceFactory`), `CompositeBackend` (routes by path prefix, longest-prefix-wins,
with a default backend), `LocalShellBackend`, `LangSmithSandbox`, `ContextHubBackend`, and the abstract
`BackendProtocol` / `SandboxBackendProtocol`.

`CompositeBackend` is directly useful here: it lets `/memories/**` or `/library/**` route to a
`StoreBackend` while everything else stays on the event-sourced backend.

```python
# ILLUSTRATIVE
backend = CompositeBackend(
    default=EventSourcedBackend(session),          # session artifacts -> event log
    routes={"/library/": StoreBackend(namespace=lambda rt: ("course", project_id))},
)
```

### 2.4 Middleware

Middleware is `langchain.agents.middleware.AgentMiddleware`. Hooks (verified in
`langchain/agents/middleware/types.py`): `before_agent`, `before_model`, `wrap_model_call`, `after_model`,
`wrap_tool_call`, `after_agent`. Decorator shorthands exist for each, plus `dynamic_prompt` (a
`wrap_model_call` convenience that just returns the system prompt) and `hook_config`.

`wrap_model_call` receives a `ModelRequest` with fields `model`, `messages`, `system_message`, `tool_choice`,
`tools`, `response_format`, `state`, `runtime`, `model_settings`. **Mutate via `request.override(...)`** —
direct attribute assignment emits a `DeprecationWarning`. `request.override()` accepts `model`,
`system_message`, `messages`, `tool_choice`, `tools`, `response_format`, `model_settings`, `state`.

That is the whole mechanism needed for stage gating: **one middleware can swap both the system prompt and
the visible tool list per model call, based on a stage field in state.**

Middleware ordering in `create_deep_agent` (from the docstring, verified against `graph.py`):

Base stack → `SkillsMiddleware` (if `skills=`), `FilesystemMiddleware`, `SubAgentMiddleware` (if inline
subagents), `SummarizationMiddleware`, `PatchToolCallsMiddleware`, `AsyncSubAgentMiddleware` (if async
subagents) → **your `middleware=` goes here** → tail stack → profile `extra_middleware`,
`_ToolExclusionMiddleware`, Anthropic/Bedrock/Fireworks prompt-caching middleware, `MemoryMiddleware` (if
`memory=`), `HumanInTheLoopMiddleware` (if `interrupt_on=`).

Consequence worth flagging: **`HumanInTheLoopMiddleware` sits in the tail, after your middleware.** A
stage-gating middleware that hides tools by overriding `request.tools` runs *before* HITL, so gating and
approval compose — but a middleware that wants to observe the interrupt decision has to look at state, not
at a hook ordering.

deepagents' own middleware, exported from `deepagents`: `FilesystemMiddleware`, `SubAgentMiddleware`,
`AsyncSubAgentMiddleware`, `MemoryMiddleware`, `RubricMiddleware`, plus `SkillsMiddleware` (importable from
`deepagents.middleware.skills`).

`RubricMiddleware(model=..., system_prompt=None, tools=None, max_iterations=3, on_evaluation=None)` is
directly relevant to instructional design: when the agent would otherwise finish, a grader subagent
evaluates the transcript against a `rubric` supplied *on invocation state*; `needs_revision` injects the
feedback as a `HumanMessage` and the loop resumes. It no-ops when no rubric is present, so it is safe to
include unconditionally. This is a ready-made "did this stage's artifact meet its criteria?" gate.

### 2.5 Subagents

`SubAgent` is a `TypedDict` (`deepagents/middleware/subagents.py`):

- Required: `name`, `description`, `system_prompt`
- Optional: `tools`, `model`, `middleware`, `interrupt_on`, `skills`, `permissions`, `response_format`

Behaviour verified in `graph.py`:

- Invoked through the `task` tool. The main agent chooses when, based on `description` — **there is no
  deepagents-level mechanism to force a particular subagent to run at a particular point.** Sequencing is
  prompt-level unless you build it.
- `tools` omitted ⇒ inherits the main agent's tools. Providing `tools` scopes the subagent.
- `interrupt_on` is inherited from the top level by declarative `SubAgent`s unless overridden;
  `CompiledSubAgent` and `AsyncSubAgent` do **not** inherit it.
- `permissions` omitted ⇒ inherits the parent's; provided ⇒ *replaces* the parent's entirely.
- Each subagent gets its own base middleware stack (`FilesystemMiddleware`, summarization,
  `PatchToolCallsMiddleware`) built against **the same backend instance**, then its `skills`, then its
  `middleware`.
- `response_format` on a subagent produces a `structured_response` that is JSON-serialized and returned as
  the `ToolMessage` content to the parent — replacing the default "last message" extraction. This is the
  clean way to get a *typed stage artifact* back from a stage subagent.
- `CompiledSubAgent` takes a pre-built `runnable` — the escape hatch for "this stage is actually a
  LangGraph state machine."
- `AsyncSubAgent` (identified by a `graph_id` key) routes to `AsyncSubAgentMiddleware` and runs as a
  background task with launch/check/update/cancel/list tools. Requires a deployed graph; not applicable to
  this repo's single-process setup without a LangGraph server. **UNVERIFIED** whether it works against a
  purely local, non-deployed graph.

### 2.6 Harness profiles

`HarnessProfile` / `HarnessProfileConfig` / `register_harness_profile` and `ProviderProfile` /
`register_provider_profile` let you attach per-model behaviour: `base_system_prompt`,
`system_prompt_suffix`, `excluded_tools`, `excluded_middleware`, `extra_middleware`,
`tool_description_overrides`, and `general_purpose_subagent`. Built-in profiles exist for Anthropic
Haiku 4.5 / Sonnet 4.6 / Opus 4.7, OpenAI Codex, and NVIDIA Nemotron 3 Ultra.

This is the only supported way to *remove* a built-in tool. Excluding protected scaffolding
(`FilesystemMiddleware`, `SubAgentMiddleware`) raises `ValueError`, as does an exclusion entry that matches
nothing.

Relevant to this repo: the local OpenAI-compatible endpoint will not match any built-in profile, so the
default (empty base prompt, all tools) applies. **UNVERIFIED**: exactly which profile, if any, a
`ChatOpenAI` pointed at a custom `base_url` resolves to — I read the dispatch (`_harness_profile_for_model`)
but did not execute it.

### 2.7 Interrupts, checkpointing, streaming

- Interrupts require a checkpointer. `interrupt_on={"tool_name": True | InterruptOnConfig(...)}`.
  `InterruptOnConfig` carries `allowed_decisions` and a `when` predicate.
- `permissions=[FilesystemPermission(operations=[...], paths=[...], mode="allow"|"deny"|"interrupt")]` is a
  path-scoped alternative; interrupt-mode rules auto-install `HumanInTheLoopMiddleware` and merge with
  `interrupt_on` (user entries win per tool name). First matching rule wins; no match ⇒ allowed.
- Resume: `Command(resume={"decisions": [{"type": "approve"|"edit"|"reject"|"respond", ...}]})`, one
  decision per action request, positionally paired.
- The published docs show `agent.invoke(..., version="v2")` and `result.interrupts`; the repo reads
  `state["__interrupt__"]` off the `values` stream instead. Both work in 0.7.1 — the repo's path is
  verified by its own passing tests. I did **not** verify whether `version="v2"` changes interrupt payload
  shape; **UNVERIFIED**, and worth a spike before adopting the documented form.
- Streaming: `stream_mode` accepts a list. `"values"`, `"messages"`, `"updates"`, `"custom"` are the
  LangGraph modes. `subgraphs=True` adds an `ns` namespace tuple per chunk, which is how the docs attribute
  subagent output.
- Tools may return `langgraph.types.Command(update={...})` to write graph state
  (`langgraph/prebuilt/tool_node.py` handles `Command` outputs). This is the mechanism a "workflow-as-tools"
  design would use to advance a stage field.

### 2.8 LangGraph underneath

`create_deep_agent` returns a `CompiledStateGraph`, so everything LangGraph offers is available: it can be
a node in a larger graph, wrapped by `StateGraph`, given a persistent `Checkpointer` (Postgres/SQLite
savers) and a `BaseStore`, or compiled into a `CompiledSubAgent`. The default state is `DeepAgentState`,
which is `AgentState` plus a `DeltaChannel` reducer on `messages` (O(N) instead of O(N²) checkpoint growth).

---

## 3. Exposing structured multi-stage workflows to deepagents

**The problem.** Offer selectable, staged instructional-design workflows — Backward Design / UbD, ADDIE,
Tyler's Model — that an agent runs against unstructured research to produce course materials. Each has an
ordered stage sequence with distinct outputs, and stages have real ordering constraints (you cannot design
assessments before you have stated outcomes).

Constraints coming from this repo specifically, which narrow the options a lot:

1. **The agent is rebuilt every turn** and the checkpointer is per-turn and in-memory. Any state that must
   survive a turn boundary has to live in the aggregate (events), not in LangGraph state.
2. **Persistence is event-sourced through the filesystem backend.** A stage artifact written to a path is
   already durable and auditable, for free.
3. **Human review already has a mechanism**: `interrupt_on` + the approval resume loop, with every decision
   recorded as `RecordToolDecision`.
4. **Streaming already has a mechanism**: the two-mode astream → `ActivityReporter` → SSE. It currently
   distinguishes only main-agent vs. not.
5. The model is a local OpenAI-compatible one at `temperature=0`. **Instruction-following reliability is
   the binding constraint on any prompt-only design.**

### Option 1 — Workflow-as-prompt

Inject the chosen methodology's stage sequence into the system prompt, as another suffix alongside
`DELEGATION_PROMPT` / `SEARCH_PROMPT` / `KNOWLEDGE_PROMPT`.

```python
# ILLUSTRATIVE
BACKWARD_DESIGN_PROMPT = """
Work in three stages, in order, and do not begin a stage until the previous one
is written to a file.

STAGE 1 — Desired results. Write /course/01-desired-results.md ...
STAGE 2 — Evidence. Write /course/02-evidence.md ...
STAGE 3 — Learning plan. Write /course/03-learning-plan.md ...
"""

WORKFLOWS = {"backward-design": BACKWARD_DESIGN_PROMPT, "addie": ADDIE_PROMPT, ...}
prompt_suffix += WORKFLOWS[chosen]
```

- **Artifacts**: files, via the existing backend. Already event-sourced. No new machinery.
- **Review gates**: only via existing `interrupt_on` on `write_file`, which is stage-blind — it gates every
  write identically. You could add a `FilesystemPermission(operations=["write"], paths=["/course/**"],
  mode="interrupt")` to at least scope it to artifacts.
- **Streaming**: works unchanged. But the UI has no way to *know* which stage is running except by parsing
  prose or watching file paths.
- **Trade-offs**: near-zero implementation cost, zero new failure modes, fully compatible with everything
  already built. But the workflow is advisory. A local model can skip a stage, merge two, or produce a
  Stage 3 that never had a Stage 1. Nothing structural prevents it, and nothing detects it. There is no
  selectable-workflow *state* the UI can render.

**Verdict**: the right baseline and the right fallback, not the right answer alone.

### Option 2 — Workflow-as-subagents

One `SubAgent` per stage; the main agent is an orchestrator that sequences them via `task`.

```python
# ILLUSTRATIVE
BACKWARD_DESIGN_SUBAGENTS = [
    {
        "name": "stage-desired-results",
        "description": "UbD Stage 1. Produces enduring understandings, essential "
                       "questions, and transfer goals from the research corpus.",
        "system_prompt": STAGE_1_PROMPT,
        "tools": [graph_search, read_file, write_file],   # scoped: no web search
        "response_format": DesiredResults,                # typed artifact back to parent
    },
    {"name": "stage-evidence", ...},
    {"name": "stage-learning-plan", ...},
]
```

- **Artifacts**: two channels at once. Files via the shared backend (event-sourced), *and* a typed
  `structured_response` returned as the `ToolMessage` content to the orchestrator — which is genuinely
  attractive, because it gives the parent a validated object rather than prose.
- **Review gates**: per-stage `interrupt_on` on the subagent spec, inherited from the top level by default
  and overridable per stage. So Stage 1 can gate `write_file` while Stage 3 does not.
- **Streaming**: needs work. The current `to_activity_delta` filters on `langgraph_node == "model"`, which
  *excludes* subagent tokens by design. Rendering per-stage progress requires `subgraphs=True` and
  attribution by namespace, i.e. a real change to `deep_agent.py`.
- **Trade-offs**: strong context hygiene (each stage starts fresh, tool noise stays out of the
  orchestrator) and honest tool scoping. But **ordering is still the orchestrator's choice**, made in
  prose — deepagents has no way to require that `stage-evidence` runs after `stage-desired-results`. And
  `delegation.py` in this repo already documents the Cognition objection precisely on point: subagents that
  each produce *part of an artifact* make conflicting implicit decisions the parent must reconcile. Course
  materials are exactly that kind of constructive, interdependent work. The repo's own guidance steers
  delegation toward investigation, not construction.

**Verdict**: right shape for the *work* inside a stage; wrong mechanism for *sequencing* stages.

### Option 3 — Workflow-as-tools

Each stage is a tool. The tool advances stage state and returns a `Command(update=...)`; its precondition
check refuses out-of-order calls.

```python
# ILLUSTRATIVE
@tool
def complete_stage(stage: str, artifact_path: str, runtime: ToolRuntime) -> Command:
    """Mark an instructional-design stage complete and unlock the next one."""
    plan = runtime.state["workflow"]
    if stage != plan.next_stage:
        return f"Cannot complete {stage}: {plan.next_stage} has not been done."
    return Command(update={"workflow": plan.advance(stage, artifact_path)})
```

- **Artifacts**: the stage *content* still goes through `write_file` (event-sourced); the tool records the
  transition. To make transitions durable in this repo, `complete_stage` should also execute a domain
  command on the aggregate, the same way the knowledge tools reach a port — otherwise the transition lives
  only in the per-turn `MemorySaver` and is lost at the turn boundary.
- **Review gates**: excellent fit. Put `complete_stage` in `GATED_TOOLS` and the existing approval loop
  gives you "a human signs off each stage" with a `RecordToolDecision` event per sign-off, essentially for
  free. This is the cheapest path to real review gates in this codebase.
- **Streaming**: works unchanged. Tool calls already surface through `to_activity_message`
  (`describe_activity` renders `complete_stage(...)`), so the UI can derive current stage from the activity
  feed without any change to `deep_agent.py`.
- **Trade-offs**: enforces ordering *reactively* — the model can still call the wrong tool, it just gets
  refused and has to retry, which burns tokens and can confuse a weaker local model. It does not prevent
  the model from doing Stage 3 *work* before Stage 1; it only prevents it from claiming completion. Good
  bookkeeping, partial enforcement.

**Verdict**: the best cost-to-benefit ratio for gates and for UI stage state. Insufficient alone for
enforcement.

### Option 4 — Workflow-as-graph

A LangGraph `StateGraph` with one node per stage, each node being a `create_deep_agent(...)` instance (or
the same one with a stage-specific prompt), edges encoding the methodology.

```python
# ILLUSTRATIVE
builder = StateGraph(CourseState)
builder.add_node("desired_results", make_stage_agent(STAGE_1))
builder.add_node("evidence",        make_stage_agent(STAGE_2))
builder.add_node("learning_plan",   make_stage_agent(STAGE_3))
builder.add_edge(START, "desired_results")
builder.add_edge("desired_results", "evidence")
builder.add_edge("evidence", "learning_plan")
builder.add_edge("learning_plan", END)
workflow = builder.compile(checkpointer=..., interrupt_before=["evidence", "learning_plan"])
```

- **Artifacts**: same file backend, plus typed fields on `CourseState` per stage.
- **Review gates**: the strongest available — `interrupt_before` on a *node* is a stage boundary, not a tool
  call. A human reviews the completed Stage 1 artifact before Stage 2 starts, structurally.
- **Streaming**: needs `subgraphs=True`; node names give clean stage attribution, arguably better than any
  other option.
- **Trade-offs**: this is the only option that makes stage order **impossible to violate**. It is also the
  largest change to this codebase. `DeepAgentTurnExecutor` currently owns one agent, one thread, one resume
  loop, and streams two modes; wrapping a multi-node graph means the executor's contract
  ("run one pass over these messages, return new messages") no longer describes what happens. The
  per-turn `MemorySaver` is wrong for a graph that spans turns — you would need a durable checkpointer, at
  which point there are two sources of truth (the checkpoint and the event log) and the repo's whole
  "the log is the record" invariant is under pressure. It also fits the *conversational* product poorly:
  a user who wants to revisit Stage 1 after seeing Stage 3 has to fight the graph.
- Middle path worth noting: compile the graph once and hand it to `create_deep_agent` as a
  `CompiledSubAgent`. The conversation stays a deep agent; the *methodology run* is one deterministic
  delegated call. This preserves the current executor contract almost entirely. **UNVERIFIED**: whether a
  `CompiledSubAgent` sharing the same `EventSourcedBackend` records writes on the aggregate the same way —
  it does not inherit `state_schema` or `interrupt_on`, so it would have to be compiled with the backend
  wired in explicitly.

**Verdict**: correct if the product is a *pipeline*. Overweight if the product is a *conversation that
follows a methodology*. The `CompiledSubAgent` middle path deserves a spike.

### Option 5 — Middleware-driven stage gating

A custom `AgentMiddleware` holds the stage in graph state, and on every model call swaps in the current
stage's prompt and restricts the tool list to what that stage may use.

```python
# ILLUSTRATIVE
class StageMiddleware(AgentMiddleware):
    def __init__(self, workflow: Workflow) -> None:
        self._workflow = workflow

    def wrap_model_call(self, request, handler):
        stage = self._workflow.stage_for(request.state.get("stage_index", 0))
        return handler(
            request.override(
                system_message=SystemMessage(stage.prompt),
                tools=[t for t in request.tools if t.name in stage.allowed_tools],
            )
        )

    def after_model(self, state, runtime):
        # advance when this stage's artifact exists and the model stopped calling tools
        ...
```

- **Artifacts**: files, unchanged; the stage index is middleware-contributed state (the pattern the
  `create_deep_agent` docstring explicitly recommends over a custom `state_schema`).
- **Review gates**: compose cleanly. Your middleware runs *before* the tail `HumanInTheLoopMiddleware`, so
  tool restriction and approval stack. A stage transition can additionally be made an interruptible tool
  (Option 3) so a human confirms it.
- **Streaming**: unchanged for prose. The middleware can emit stage transitions on LangGraph's `"custom"`
  stream mode, or — more in keeping with this codebase — call a callback that feeds the existing
  `ActivityReporter`, giving the UI an explicit "Stage 2 of 3: Evidence" without parsing anything.
- **Trade-offs**: the enforcement is real where it counts — a tool the model cannot see is a tool it cannot
  call, so "no assessment-writing tool until outcomes exist" is structural, not advisory. It costs one
  class, no change to the executor's contract, and no second source of truth. The weak point is the
  *advance* condition: `after_model` has to decide when a stage is done, and that decision is either
  heuristic (artifact file exists) or model-driven (an explicit transition tool). Also, per-call prompt
  swapping defeats prompt caching — irrelevant for the local model here, relevant if this ever points at
  Anthropic.

**Verdict**: the best structural enforcement available without restructuring the executor.

### Comparison

| | Ordering enforced | Review gates | Stage state for UI | Streaming changes | Cost | Fits current executor |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Prompt | No | Coarse only | None | None | Trivial | Yes |
| 2 Subagents | No (prose) | Per-stage | Weak | `subgraphs=True` | Medium | Mostly |
| 3 Tools | Reactive | Excellent (reuses approval loop) | Good | None | Low | Yes |
| 4 Graph | Structural | Strongest (`interrupt_before`) | Best | `subgraphs=True` | High | No |
| 5 Middleware | Structural (tool visibility) | Good, composes with HITL | Good | Optional | Low-medium | Yes |

---

## 4. Recommendation

**Compose 5 + 3 + 1, and keep 2 for intra-stage work. Do not adopt 4 for the conversational product.**

Concretely:

1. **Workflow definitions as data.** A `Workflow` value object in the domain/application layer: ordered
   stages, each with a name, prompt fragment, allowed tool names, expected artifact path, and completion
   criteria. `BACKWARD_DESIGN`, `ADDIE`, `TYLER` are three instances. This is framework-free and lives
   where the architecture test wants it.

2. **A `StageMiddleware` in `infrastructure/agent/`** (Option 5), passed via the currently-unused
   `middleware=` parameter. It swaps the system prompt and filters `request.tools` per stage in
   `wrap_model_call`. This gives real enforcement — the model cannot call what it cannot see — for the cost
   of one class, with no change to `DeepAgentTurnExecutor`'s contract.

3. **An `advance_stage` tool** (Option 3) that executes a domain command on the `CodingSession` aggregate,
   so transitions are events and survive the turn boundary — the per-turn `MemorySaver` cannot be trusted
   for anything durable. Add it to `GATED_TOOLS` and the existing approval machinery gives you human
   sign-off per stage with a `RecordToolDecision` per approval, and the web UI's approval prompt already
   renders it. This is the single highest-leverage piece: it reuses infrastructure that already exists and
   is already tested.

4. **Stage prompts remain prompts** (Option 1). The middleware is the enforcement; the prompt is still what
   makes the model good at the stage. Both are needed.

5. **Stage artifacts are files** at fixed paths per stage, so persistence, audit, and replay are the
   existing event-sourced path with nothing new. Consider a `FilesystemPermission` scoping
   `/course/**` writes.

6. **Subagents (Option 2) for research-heavy work inside a stage** — surveying the corpus, checking the
   knowledge graph — not for producing stage artifacts. That is exactly the line `delegation.py` already
   draws, and course materials are the interdependent constructive work it warns against splitting.

7. **`RubricMiddleware` is a strong candidate for per-stage quality gates** — pass the stage's completion
   criteria as the rubric and let a grader loop before the stage is allowed to advance. Worth a spike; it
   costs one extra model per stage and its behaviour against a local model is **UNVERIFIED**.

8. **UI stage state comes free**: the `advance_stage` tool call already flows through `to_activity_message`
   to SSE. Adding an explicit stage field to the activity payload is a small presenter change, not a
   streaming redesign.

Things to spike before committing the spec:

- Whether the local model reliably respects a restricted tool list (it should — restriction is enforced at
  request assembly, not by persuasion — but confirm the endpoint doesn't choke on the tool set changing
  between calls within one conversation).
- Which harness profile, if any, resolves for `ChatOpenAI(base_url=...)` — it determines whether a
  `base_system_prompt` is silently prepended to your stage prompts.
- Whether `TodoListMiddleware()` is worth adding; deepagents does not install it by default here, and a
  visible plan may substitute for or duplicate the stage machinery.
- `CompiledSubAgent` + shared `EventSourcedBackend`, if the pipeline-shaped Option 4 is ever wanted for a
  "run the whole methodology unattended" mode alongside the conversational one.

---

## 5. Stage-Gating Middleware: Verified API Surface

Everything in this section was read out of `langchain==1.3.14`
(`langchain/agents/middleware/types.py`, `langchain/agents/factory.py`) or executed against the installed
environment. Line references are to those files.

### 5.1 The `AgentMiddleware` base class

**Import**: `from langchain.agents.middleware import AgentMiddleware` (re-exported from
`langchain.agents.middleware.types`). deepagents does not define its own base class — its middleware
subclass langchain's.

```python
class AgentMiddleware(Generic[StateT, ContextT, ResponseT]):
    state_schema: type[StateT] = _DefaultAgentState   # class attribute
    tools: Sequence[BaseTool]                          # extra tools this middleware registers
    transformers: Sequence[TransformerFactory] = ()    # stream transformer factories

    @property
    def name(self) -> str: ...   # defaults to class name
```

**Every hook exists in both a sync and an `a`-prefixed async form.** Verified full list
(`types.py:419-800`):

| Sync | Async | Signature |
| --- | --- | --- |
| `before_agent` | `abefore_agent` | `(self, state: StateT, runtime: Runtime[ContextT]) -> dict[str, Any] \| None` |
| `before_model` | `abefore_model` | same as above |
| `after_model` | `aafter_model` | same as above |
| `after_agent` | `aafter_agent` | same as above |
| `wrap_model_call` | `awrap_model_call` | `(self, request: ModelRequest[ContextT], handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse \| AIMessage \| ExtendedModelResponse` |
| `wrap_tool_call` | `awrap_tool_call` | `(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage \| Command]) -> ToolMessage \| Command` |

The four state hooks return **state updates** (a dict merged into graph state) or `None`. The two `wrap_*`
hooks receive a `handler` they may call zero times (short-circuit), once, or many times (retry).

> **This is a spec-changing finding.** The default `awrap_model_call` body **raises
> `NotImplementedError`** with an explicit message (`types.py:625-636`): *"You are likely encountering this
> error because you defined only the sync version (`wrap_model_call`) and invoked your agent in an
> asynchronous context (e.g., using `astream()` or `ainvoke()`)."* `DeepAgentTurnExecutor._invoke` uses
> `agent.astream(...)`. **A `StageMiddleware` for this repo must implement `awrap_model_call`, not
> `wrap_model_call`.** Same rule for the other five hooks. The `@wrap_model_call` decorator on a standalone
> `async def` function is the documented alternative.

Decorator shorthands, all exported from `langchain.agents.middleware`: `before_agent`, `before_model`,
`after_model`, `after_agent`, `wrap_model_call`, `wrap_tool_call`, `dynamic_prompt`, `hook_config`. Each
accepts `state_schema=`, `tools=`, `name=` kwargs to configure the generated middleware class.

### 5.2 `ModelRequest` — attributes and how to override them

Dataclass at `types.py:86-200`. Attributes:

`model`, `messages` (excludes the system message), `system_message: SystemMessage | None`, `tool_choice`,
`tools: list[BaseTool | dict]`, `response_format`, `state: AgentState`, `runtime: Runtime[ContextT]`,
`model_settings: dict`.

`request.system_prompt` is a **read-only property** returning `self.system_message.text` (or `None`).

**Mutation**: `ModelRequest.__setattr__` is overridden to emit a `DeprecationWarning` on *every* direct
attribute assignment (`types.py:167`). It still writes through — so `request.tools = [...]` does technically
work today — but it is explicitly deprecated. Assigning `request.system_prompt = "..."` is special-cased to
convert into a `SystemMessage`.

**Use `request.override(**kwargs)`** (`types.py:201`). It is immutable — returns a *new* `ModelRequest`,
leaving the original untouched. Accepted keys (`_ModelRequestOverrides`, `types.py:72-84`): `model`,
`system_message`, `messages`, `tool_choice`, `tools`, `response_format`, `model_settings`, `state`.
(`system_prompt` is accepted but deprecated.) You must **return** or **pass on** the overridden request —
`override` has no side effect on the original.

```python
# ILLUSTRATIVE — the shape a StageMiddleware needs
async def awrap_model_call(self, request, handler):
    stage = ...
    return await handler(
        request.override(
            system_message=SystemMessage(stage.prompt),
            tools=[t for t in request.tools if t.name in stage.allowed_tools],
        )
    )
```

**Does overriding `tools` actually change what's bound to the model? Yes — verified.**
`factory.py:1349` does `final_tools = list(request.tools)` and `factory.py:1367` calls
`request.model.bind_tools(final_tools, **bind_kwargs)`. `request.tools` after the middleware chain is
authoritative for the bind.

Two caveats, both verified:

- **Filtering down is safe. Adding up is not.** `factory.py:113-130` defines
  `DYNAMIC_TOOL_ERROR_TEMPLATE`: *"Middleware added tools that the agent doesn't know how to execute… This
  happens when middleware modifies `request.tools` in `wrap_model_call` to include tools that weren't
  passed to `create_agent()`."* The fix is to register the tool up front (via `create_deep_agent(tools=...)`
  or the middleware's own `tools` attribute) and *hide* it per stage, rather than conjuring it. That is
  exactly the recommended design: register the full union of stage tools once, filter per stage.
- `request.tools` at the point your middleware sees it already contains the deepagents built-ins
  (`read_file`, `write_file`, `task`, …) injected by `FilesystemMiddleware` / `SubAgentMiddleware`, because
  those sit *before* your middleware in the stack. A naive allowlist filter will strip the filesystem tools
  unless the stage's allowed set names them.

### 5.3 State: reading, writing, and durability

**Reading**: inside `wrap_model_call`, `request.state` is the full graph state dict. Inside
`before_model` / `after_model` / `before_agent` / `after_agent`, `state` is the first parameter. Inside a
tool, `runtime.state` via a `ToolRuntime` parameter.

**Writing**: the four state hooks return a dict that is merged as a state update. A tool can write state by
returning `langgraph.types.Command(update={...})` — `langgraph/prebuilt/tool_node.py:898,1474,1516` handles
`Command` outputs from tools. `wrap_model_call` cannot return a plain state update; it returns a
`ModelResponse` (or `ExtendedModelResponse` carrying commands).

**Extension mechanism**: set `state_schema` as a **class attribute** on the middleware. `factory.py:1154`
collects `[*(m.state_schema for m in middleware), base_state]` and merges them via `_resolve_schemas`, with
`base_state` **last so it wins any field conflict**. So middleware-contributed fields are additive and
cannot clobber the caller's explicit `state_schema`. This is why the `create_deep_agent` docstring
recommends middleware state over a custom `state_schema`.

```python
# ILLUSTRATIVE
class StageState(AgentState):
    stage_index: int
    workflow_name: str

class StageMiddleware(AgentMiddleware):
    state_schema = StageState
```

Also verified: `factory.py:1080` raises `AssertionError("Please remove duplicate middleware instances.")`
if two middleware share a `name`. Middleware names must be unique.

**Durability — the answer is: graph state does NOT survive the turn.**

`DeepAgentTurnExecutor._invoke` constructs `MemorySaver()` inline on every call and uses
`thread_id = f"{session.aggregate_id}:{session.state.turn_index}"`. Two independent reasons the state is
gone at the next turn: the saver object is discarded, and the thread id changes anyway. LangGraph state is
therefore scoped to *one turn*, and exists only so the interrupt/resume loop has somewhere to park.

**Consequence: stage must be reconstructed from the event log at agent-build time.** The middleware's state
field is a per-turn cache of a fact whose source of truth is the aggregate. Reconstruction looks like this:

```python
# ILLUSTRATIVE
# 1. advance_stage tool executes a domain command -> event on the aggregate
@tool
async def advance_stage(stage: str, artifact_path: str) -> str:
    """Record an instructional-design stage as complete."""
    session.execute(AdvanceWorkflowStage(stage=stage, artifact_path=artifact_path))
    return f"Stage {stage} recorded."

# 2. the aggregate folds those events into current stage (domain layer)
#    session.state.workflow_stage_index

# 3. the middleware is constructed per turn, seeded from the aggregate
class StageMiddleware(AgentMiddleware):
    def __init__(self, workflow: Workflow, start_index: int) -> None:
        self._workflow, self._start = workflow, start_index

    async def abefore_agent(self, state, runtime):
        # seed per-turn graph state from the durable value
        return {"stage_index": state.get("stage_index", self._start)}

    async def awrap_model_call(self, request, handler):
        stage = self._workflow.stages[request.state.get("stage_index", self._start)]
        ...

# 4. built fresh each turn, like the agent itself
create_deep_agent(..., middleware=[StageMiddleware(workflow, session.state.workflow_stage_index)])
```

Note the constructor takes the seed rather than the middleware reading a mutable attribute — the
`create_deep_agent` docs warn explicitly against mutating middleware instance attributes (race conditions);
graph state is the sanctioned channel *within* a turn, the event log *across* turns.

### 5.4 Ordering and composition

Verified in `factory.py`:

- **Node hooks run in declaration order on the way in, reverse order on the way out.**
  `before_agent` and `before_model` nodes are chained with `itertools.pairwise(...)` in list order
  (`factory.py:1716-1733`); `after_model` and `after_agent` are wired from the **last** middleware backwards
  (`factory.py:1737-1740`, `1754-1765`). Classic onion: first-declared is outermost.
- **`wrap_model_call` composes right-to-left so that the first middleware in the list is the outermost
  layer** (`factory.py:319-322`, and the docstring at `types.py:597`: *"Multiple middleware compose with
  first in list as outermost layer"*). `wrap_tool_call` uses the same scheme (`factory.py:668`).
- **Graph nodes are named `f"{middleware.name}.before_model"`** etc. Relevant to this repo: the existing
  `to_activity_delta` filters on `metadata["langgraph_node"] == "model"`, and middleware nodes are *not*
  named `"model"` — so adding middleware does **not** break the current streaming discriminator.
- Hooks are only wired at all if the subclass actually overrides them (`m.__class__.before_model is not
  AgentMiddleware.before_model`), so an unimplemented hook costs nothing.

**Composition with the existing `interrupt_on=`**: clean, verified by ordering. `create_deep_agent` places
`HumanInTheLoopMiddleware` in the **tail stack, after your `middleware=`** (docstring, verified against
`graph.py`). Since your middleware is outermost for `wrap_model_call`, the tool filtering happens before the
model is bound; HITL then gates whichever of the surviving tools the model actually calls. A tool hidden by
the stage filter simply never reaches the interrupt config, and a gated tool that *is* visible still
interrupts exactly as today. Adding `advance_stage` to `GATED_TOOLS` composes with both.

One thing to watch: `interrupt_config(policy)` builds an entry per tool name in `GATED_TOOLS` regardless of
whether the tool is currently visible. That is harmless — an entry for an absent tool never fires.

### 5.5 Harness profile for `ChatOpenAI(base_url=...)` — RESOLVED

Executed against the installed environment:

```
>>> m = ChatOpenAI(model='qwen3-coder', base_url='http://localhost:1234/v1', api_key='x')
>>> p = _harness_profile_for_model(m, None)
profile: HarnessProfile   name: None
base_system_prompt: None
system_prompt_suffix: None
excluded_tools: frozenset()
extra_middleware: ()
```

**A bare default `HarnessProfile` resolves.** Nothing is prepended or appended to the system prompt, no
tools are excluded, no extra middleware is injected. So `system_prompt=` reaches the model verbatim, and
stage prompts swapped in via `request.override(system_message=...)` are the complete authored system
prompt — no hidden `BASE`/`SUFFIX` to account for.

Caveat worth stating: this holds because the local endpoint's model name matches no registered profile. If
the deployment ever points at a real `anthropic:` or `openai:codex` model, a profile *will* match and will
prepend a `base_system_prompt`. A stage middleware that replaces `system_message` wholesale would silently
discard that profile content. **UNVERIFIED**: whether `request.system_message` as seen by middleware already
has the profile's `BASE`/`SUFFIX` merged in (in which case replacing it drops them) or not. On the current
local-model setup the question is moot; it becomes real on a model switch, and the safe pattern is to
*append* the stage prompt to `request.system_message` rather than replace it.
