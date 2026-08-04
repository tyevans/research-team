# SearXNG Search Tool, Gated by Human-in-the-Loop — Design

**Date:** 2026-08-03
**Status:** Approved

## Purpose

Give the agent a web search tool backed by a SearXNG instance, and introduce
human-in-the-loop approval at the same time — because the search tool is the
first thing this agent does that reaches outside the process, and an ungated
network call would quietly retire a property the system currently advertises.

The two ship together on purpose. Search without a gate trades a documented
guarantee for a feature. The gate is what keeps the trade explicit.

Autonomy is adjustable at any time, per tool, at three levels: `auto`, `ask`,
`deny`. It is not fixed at startup and not global.

## What this changes about the sandbox claim

The original design's non-goals include *"No shell/exec tool"*, and its purpose
section states that no side effect escapes the process.

*(Amended 2026-08-03.)* Two of the three claims survive intact:

- **The filesystem sandbox survives.** The agent still has no shell and no real
  filesystem. Nothing it writes escapes the process.
- **Replay purity survives.** Search results are recorded as ordinary
  `ToolResultRecorded` conversation messages, so refolding the log replays the
  results that were actually returned. Replay never re-fetches, and a refold
  years later reproduces the same session even if the SearXNG instance is gone.
- **Network egress becomes a documented, gated exception.** This is the real
  change. It is opt-in (no `AGENT_SEARXNG_URL`, no tool) and gateable per tool.

## Non-Goals

- **No durable suspension across process restart.** A turn interrupted for
  approval lives in memory. If the process dies mid-approval the turn is
  discarded and recorded as `TurnFailed`, which is already the log's semantics
  for an abandoned turn. Making approval durable is a larger change to the turn
  lifecycle (see *Alternatives*, approach C) and is deliberately deferred.
- **No approval UI beyond accept / reject / edit-args.** Whatever deepagents'
  `InterruptOnConfig` offers, nothing more.
- **No search result caching, ranking, or re-querying.** The tool returns what
  the instance returned.
- **No gating of read-only file tools.** `read_file`, `glob`, `grep` stay
  autonomous. They cost nothing and escape nothing.

## Architecture

```
   AutonomyPolicy (application/autonomy.py)  ── mutable, shared, per-session
        │  level_for(tool) -> auto | ask | deny
        │
        ├──► when=  predicate on InterruptOnConfig     (auto vs. not-auto)
        │            evaluated per tool call, so a level
        │            change lands on the next call, mid-turn
        │
        └──► resume loop in DeepAgentTurnExecutor      (ask vs. deny)
                 │
                 ├── deny → auto-reject, no human asked
                 │          ToolCallDecided(decided_by="policy")
                 │
                 └── ask  → ApprovalPort.decide(...)
                            ToolCallDecided(decided_by="human")
                                 │
                    ┌────────────┴────────────┐
              CLI adapter               Web adapter
              (prompt in repl)          (SSE out, POST back)
```

### 1. The policy — `research_team/application/autonomy.py`

```python
Level = Literal["auto", "ask", "deny"]

class AutonomyPolicy:
    """Mutable, consulted per tool call rather than at agent construction."""
    def level_for(self, tool_name: str) -> Level: ...
    def set(self, tool_name: str, level: Level) -> None: ...
```

Mutable by design, and held on `Application` so the REPL and the web UI mutate
one object. Because the `when` predicate closes over it and langchain evaluates
that predicate per tool call, raising or lowering autonomy takes effect on the
next tool call — including partway through a turn already in flight. That is
the whole reason autonomy is a live object rather than a constructor argument.

Gated tools in this first cut: the search tool, `write_file`, `edit_file`,
`delete_file`. Default level is `auto` for all of them, so existing behaviour is
unchanged until someone asks for a gate.

**Why `when` cannot express three levels.** `InterruptOnConfig.when` returns a
bool: interrupt, or don't. So the three levels are split across two places —
`when` answers *auto vs. not-auto*, and the resume loop answers *ask vs. deny*
by auto-rejecting denied calls without troubling a human. Both halves read the
same policy object, so there is still one source of truth.

### 2. The tool — `research_team/infrastructure/agent/search.py`

A langchain `@tool` over SearXNG's JSON API:

```
GET {base}/search?q=<query>&format=json
```

Results are capped and flattened to title, URL, and snippet. An uncapped search
result is a context leak of exactly the kind the `elide` and `compact`
strategies exist to clean up afterwards; cheaper not to make the mess.

The tool is constructed only when `AGENT_SEARXNG_URL` is set, so a default
install registers no network tool at all and the sandbox claim holds unmodified
for anyone who has not opted in.

### 3. The executor — resume loop in `DeepAgentTurnExecutor._invoke`

`create_deep_agent` gains two arguments it is not currently passed: `tools=` and
`interrupt_on=`. `checkpointer=None` becomes a per-turn `MemorySaver` with a
thread id derived from session id and turn index.

**Why a checkpointer is not optional here.** Verified against the installed
versions: `interrupt()` without a checkpointer halts the graph and returns
`__interrupt__` in the state, but the subsequent `Command(resume=...)` raises
`RuntimeError: Cannot use Command(resume=...) without checkpointer`. With a
`MemorySaver` it resumes correctly. HITL therefore forces the checkpointer.

The single `astream` pass becomes a loop:

1. Stream the agent, reporting activity as it already does.
2. If the final state carries `__interrupt__`, resolve each interrupted call —
   `deny` auto-rejects, `ask` goes to the `ApprovalPort`.
3. Resume with `Command(resume=...)` and stream again.
4. Repeat until a pass completes with no interrupt.

Activity reporting during resumed passes must not double-count messages the
caller has already seen; the existing `reported` cursor carries across passes.

### 4. The approval port — `research_team/application/ports.py`

```python
class ApprovalPort(Protocol):
    async def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...
```

The executor learns nothing about *how* a human is asked, matching how every
other outside-world concern in this codebase is declared as a port next to its
caller and implemented in `infrastructure`.

Two adapters:

- **CLI** — prompts in the REPL, in the same place turn activity already prints.
- **Web** — pushes the request over the existing SSE feed and takes the decision
  back over a POST, against a registry of pending approvals keyed by session.

### 5. Events — `research_team/domain/events.py`

```python
@register_event
class ToolCallDecided(DomainEvent):
    aggregate_type: str = "CodingSession"
    tool_name: str
    args: dict[str, Any]
    decision: str          # "approve" | "edit" | "reject" | "respond"
    decided_by: str        # "human" | "policy"
    edited_args: dict[str, Any] | None = None

@register_event
class AutonomyChanged(DomainEvent):
    aggregate_type: str = "CodingSession"
    tool_name: str
    level: str
```

Both are added to `SESSION_EVENTS`, and both get a case in
`tests/infrastructure/test_schema_evolution.py` — the events module's own
docstring makes that mandatory for any new event shape.

**Why autonomy is session-scoped rather than process-scoped.** A supervision
level is a fact about how a session was conducted. Recording it on the stream
lets the log answer "was this turn supervised, and by whom?" — which is the
question an audit trail exists to answer, and one that is not recoverable later
from configuration that may since have changed. It also means a fork inherits
the supervision level along with everything else it inherits.

### 6. Prompt and documentation

A search-usage prompt fragment in the shape of `DELEGATION_PROMPT`, added at
composition time when the tool is registered. README gains `AGENT_SEARXNG_URL`
in the configuration table and an honest note about the gated-egress exception.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_SEARXNG_URL` | *(unset)* | SearXNG base URL. Unset means no search tool. |
| `AGENT_SEARXNG_RESULTS` | `5` | Max results returned into context per query. |

`config.py` stays the only module that reads the environment.

## Dependencies

`httpx` moves from the `dev` group to project dependencies. It is already
present and already used in tests, so this is a promotion rather than a new
dependency.

`hypothesis` and `mutmut` join the `dev` group. Both are test-time only and
neither is imported by shipped code.

## Error handling

- **SearXNG's JSON format is disabled by default**; an instance needs
  `formats: [json]` in `settings.yml`. The tool must detect a non-JSON response
  and return a legible message naming that setting, rather than surfacing a
  parse error the model will try to reason about.
- **Instance unreachable or slow** — bounded timeout, returned to the model as
  an error tool result. A failed search is an ordinary tool failure, recorded
  with `is_error=True` like any other; it is not a turn failure.
- **Rejected call** — the model receives a tool result saying the call was
  refused, and continues. Refusal is information, not an exception.
- **Approval adapter disappears mid-turn** (browser closed, REPL killed) — the
  turn fails and is discarded whole, exactly as any other mid-turn failure is.

## Testing

- **Policy** — levels, defaults, and mutation taking effect between calls.
- **Resume loop** — a scripted model plus a fake `ApprovalPort` covering accept,
  reject, edit-args, and deny-without-asking. This is the piece most likely to
  break, and the only piece where the loop's message accounting can drift.
- **Search tool** — against a stubbed httpx transport: normal results, non-JSON
  response, timeout. No live network.
- **A `live`-marked test** against a real instance, following the existing
  marker convention in `pyproject.toml` (deselected by default).
- **Schema evolution** — a case for each of the two new events.

### Property-based tests (Hypothesis)

Example-based tests confirm the cases we thought of. The policy and the resume
loop both have state spaces small enough to describe and large enough to hide a
case, so they get properties rather than only examples:

- **Policy** — for any sequence of `set` calls, `level_for` returns the last
  level set for that tool, and an untouched tool always returns the default.
  Levels never leak between tools.
- **Resume loop** — for any sequence of interrupt decisions (accept / reject /
  edit / deny, in any order and quantity), the loop terminates, every
  interrupted call receives exactly one decision, and exactly one
  `ToolCallDecided` event is recorded per interrupted call. This is the
  invariant that a hand-written example set is least likely to cover, because
  the failure mode is a miscount across resumed passes.
- **Search result formatting** — for any well-formed SearXNG JSON payload, the
  formatted output never exceeds the configured result cap and never raises.

### Mutation testing

Property tests can still be vacuous, so the suite's own strength is measured
rather than assumed. `mutmut` runs over the modules this design adds —
`application/autonomy.py`, `infrastructure/agent/search.py`, and the resume loop
— and surviving mutants are either killed with a new test or annotated with why
the mutant is equivalent. Mutation testing is scoped to the new modules, not the
whole codebase: a whole-repo run is slow enough that nobody will run it twice.

## Open question to resolve first in implementation

**Does `interrupt_on` propagate into subagents?** Gating `write_file` implies
the `worker` subagent's writes should gate too — its writes land on the same log
and are equally consequential. But subagents are separately compiled graphs, and
whether an interrupt raised inside one surfaces through the `task` tool to the
parent's resume loop is *not verified*. This must be tested before the file-tool
gating is claimed to work, not assumed. If it does not propagate, the honest
first cut gates the parent's file tools only, and says so in the README.

## Alternatives considered

**B — approval inside the tool.** The tool asks an injected approver before the
network call and returns a denial string otherwise. Much smaller: no
checkpointer, no resume loop, executor untouched, and denial is already captured
by `ToolResultRecorded`. Rejected because it is not deepagents' HITL, offers no
arg-editing, blocks awkwardly inside the graph for an async web adapter, and
does not generalise to the file tools this design gates.

**C — approval as a domain command.** The turn genuinely suspends, session state
carries "awaiting approval", and a separate command resumes it — durable across
restarts and the most faithful to event sourcing. Rejected *for now* because the
turn stops being one atomic in-process operation, which reaches into
`TurnSupervisor`, both front ends, and the read model. Worth revisiting if
approvals turn out to be long-lived in practice rather than momentary.
