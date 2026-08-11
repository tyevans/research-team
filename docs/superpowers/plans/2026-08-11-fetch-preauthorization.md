# Fetch Pre-authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person grant an autonomous research run permission to fetch from named hosts, at most N times — enforced at the approval gate, dead when the run ends — and stop an unanswerable approval from wedging a run forever.

**Architecture:** A process-local registry maps a session id to a `FetchGrant`. The run's own session is registered when the run starts and removed when it stops. Two per-turn seams consult it: `interrupt_config`, so a covered `fetch` never interrupts, and `tools_provider`, so a grant-bound `fetch` (no redirects, budget decrement) shadows the base one. `AutonomyPolicy` and `TOOL_FLOORS` are never read differently and never written.

**Tech Stack:** Python 3.13, `uv`, pytest, langchain agent middleware, eventsource-py, httpx, pydantic. No new dependencies.

## Global Constraints

- **`TOOL_FLOORS` and `AutonomyPolicy` are not modified.** Not their values, not `level_for`, not `set`. B24: "not the loop lowering `TOOL_FLOORS` itself, ever." A test asserts `TOOL_FLOORS == {"fetch": "ask", "advance_stage": "ask"}` and exists to fail if the grant is ever implemented by elevating a level.
- **The ungranted path must be byte-for-byte today's behaviour.** Every session that is not a run's session — which is nearly all of them — must fetch, gate, and time out exactly as it does now. Where a test can pin that, pin it.
- **A grant is never derived from the log at fetch time.** It lives in memory so that process death revokes it; an abandoned run must not come back authorised.
- **The model never names its own authorization.** No grant-related tool argument, no second tool name for the model to choose.
- **Do not run the full test suite** except where a task says to. Both ruff gates run over the WHOLE repository.
- **House style:** docstrings and comments carry the REASONING and state costs, not restatement.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Stage by explicit path. NEVER `git add -A`** — this repository is worked in concurrently.
- **Do not use bare `git stash` / `git stash pop`** — the stack is shared across worktrees. Write the test first; if you must set work aside, use a WIP commit or the `push -m <tag>` / `apply <sha>` / `drop` pattern CLAUDE.md prescribes.

## File Structure

| File | Responsibility |
|---|---|
| `research_team/application/grants.py` | **New.** `FetchGrant` and `GrantRegistry` — the value and the process-local store. Application layer: imports nothing but stdlib. |
| `research_team/domain/auto_research.py` | `fetch_hosts` / `fetch_budget` on `AutoRunStarted`, `StartRun`, `AutoRunState` |
| `research_team/application/auto_research.py` | Driver accepts and passes the grant; registers on start, removes in `_stop` |
| `research_team/infrastructure/agent/approval.py` | `interrupt_config` and `_gate_for` take the session and the registry |
| `research_team/infrastructure/agent/deep_agent.py` | Pass the session to `interrupt_config`; shadow registered tools with per-turn ones |
| `research_team/infrastructure/agent/fetch.py` | Grant-bound build: redirects off, budget decrement |
| `research_team/interfaces/web/approvals.py` | Bounded wait for a registered session |
| `research_team/interfaces/web/app.py` | `NewRun` fields, half-a-grant refusal |
| `research_team/application/research_supervisor.py` | Carry the grant from the route to the driver |
| `research_team/composition.py` | One registry, wired to all four consumers |

**Ordering note.** Tasks 1–2 are inert. Task 3 makes the gate consult a grant nothing yet creates. Task 7 is the first point the feature works end to end and the only task that runs all four gates.

---

### Task 1: The grant and the registry

**Files:** Create `research_team/application/grants.py`; test `tests/application/test_grants.py`

**Interfaces produced:**
- `FetchGrant(run_id: UUID, hosts: frozenset[str], budget: int)` — frozen dataclass, with `covers(url: str) -> bool` and `spend() -> None`, plus `remaining` / `spent` as needed. **`covers` must not mutate.**
- `GrantRegistry` with `register(session_id: UUID, grant: FetchGrant) -> None`, `get(session_id: UUID) -> FetchGrant | None`, `release(session_id: UUID) -> None`, and `is_unattended(session_id: UUID) -> bool` (true when a session is registered at all — Task 6 uses this).

**Design notes the implementer must honour:**
- Host matching is **exact after lowercasing**, against `urlsplit(url).hostname`. No wildcards, no suffix matching. `example.com` must NOT cover `www.example.com`, `evil-example.com`, or `example.com.attacker.net`.
- `hostname` already lowercases and strips `user:pass@`; a malformed URL must return "not covered" rather than raise, following `normalize_url`'s totality argument (`infrastructure/agent/recall.py:87-93`).
- A grant with a spent budget covers nothing. Spending is mutation on an otherwise-frozen value — put the counter somewhere that makes that explicit and say why in a docstring.
- The registry is in-memory and not thread-safe, for `Recall`'s stated reason (one loop, no interleaving). Say so.

- [ ] **Step 1: Write the failing tests.** Cover, at minimum: an exact host is covered; a subdomain is not; `evil-example.com` and `example.com.attacker.net` are not; matching is case-insensitive; `user:pass@host` is handled; a malformed URL is not covered and does not raise; a spent grant covers nothing; `covers` does not spend; register/get/release round-trips; `get` on an unknown session is `None`; `release` of an unregistered session does not raise.
- [ ] **Step 2: Run them and paste the actual failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them green.**
- [ ] **Step 5: `uv run ruff check .`, `uv run ruff format --check .`, commit by explicit path.**

---

### Task 2: The grant on the run's stream

**Files:** `research_team/domain/auto_research.py`; tests `tests/domain/test_auto_research.py`, `tests/infrastructure/test_schema_evolution.py`

**Interfaces produced:** `AutoRunStarted.fetch_hosts: list[str] = []`, `AutoRunStarted.fetch_budget: int = 0`; same two on `StartRun` and on `AutoRunState`.

- Defaults are `[]` and `0` — a run granted nothing is today's behaviour and today's payload.
- `evolve` must carry both onto `AutoRunState`, unlike `autonomy_snapshot`, which is written and never folded (`domain/auto_research.py:396-404`). The point is that "what was this run allowed to do?" becomes answerable from a fold. Say that in a docstring.
- `exhausted()` is **not** touched. The fetch budget bounds the tool, not the run.
- This modifies an event already written: `tests/infrastructure/test_schema_evolution.py` gains an `AutoRunStarted` payload with neither field, asserting it loads with `[]` and `0`.

- [ ] **Step 1: Write the failing tests**, including the schema-evolution case, following that file's established pattern of writing old payloads straight into the events table.
- [ ] **Step 2: Prove them red.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green, including every pre-existing auto-research test.**
- [ ] **Step 5: Both ruff gates; commit by explicit path.**

---

### Task 3: The gate consults the grant

**Files:** `research_team/infrastructure/agent/approval.py`, `research_team/infrastructure/agent/deep_agent.py`; tests `tests/infrastructure/test_approval.py` (find the real filename)

**Interfaces produced:** `interrupt_config(policy, *, session_id: UUID | None = None, grants: GrantRegistry | None = None)`; `_gate_for` closes over the same.

**This is the security-critical task. The `when` predicate is the authorization boundary.**

- Today: `when(request) -> bool` returns `policy.level_for(tool) != "auto"` and ignores `request` (`approval.py:39-44`). It becomes: interrupt unless the policy already says `auto`, **or** the grant covers this call.
- "Covers this call" means: the tool is `fetch`, a grant exists for this session, its budget is unspent, and the **URL argument's host** is in the allowlist. Read the URL from the request's args. If the args cannot be read, or there is no `url`, **the answer is "not covered"** — an unparseable request must never be treated as authorised.
- Only `fetch` is ever covered. A grant must not affect `write_file`, `remember`, `advance_stage` or anything else in `GATED_TOOLS`. Pin this with a test.
- `deep_agent.py:364` passes the session through. Nothing else about `_invoke` changes in this task.
- With no registry and no session — every existing caller and every test — behaviour is identical. Both parameters are keyword-only with `None` defaults for that reason.

- [ ] **Step 1: Write the failing tests.** A covered fetch does not interrupt; an uncovered host does; a spent budget does; a different gated tool always does even under a grant; an unparseable/absent `url` argument does; a grant for session A does not cover session B; with no registry, behaviour is unchanged.
- [ ] **Step 2: Prove them red.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green, plus the whole existing approval test file unchanged.**
- [ ] **Step 5: Both ruff gates; commit by explicit path.**

---

### Task 4: A per-turn tool shadows a registered one

**Files:** `research_team/infrastructure/agent/deep_agent.py`; tests alongside the executor's existing tests

**Interfaces produced:** `_invoke` composes `turn_tools` so that a tool returned by `tools_provider` replaces a registered tool of the same name.

- Today: `turn_tools = [*self._tools, *await self._resolved_tools(session)]` (`deep_agent.py:358`) — an append, so two tools could share a name.
- `application/knowledge_attachment.py:19-39` already implements this rule for `set_tools`; reuse it if it can be imported cleanly, otherwise mirror it and say in a comment why there are two copies.
- **Order matters:** the per-turn tool wins. Pin it with a test that would fail if the precedence were reversed.
- This task is behaviour-preserving for every existing caller — nothing currently returns a colliding name. Say so in the commit message, and note that two tools sharing a name is silently possible today, which is the independent reason to fix it.

- [ ] **Step 1: Write the failing test** — a per-turn tool named the same as a registered one replaces it, and the registered one is not also present.
- [ ] **Step 2: Prove it red.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green, plus the executor's existing tests.**
- [ ] **Step 5: Both ruff gates; commit by explicit path.**

---

### Task 5: The grant-bound fetch

**Files:** `research_team/infrastructure/agent/fetch.py`; tests `tests/infrastructure/test_fetch.py`

**Interfaces produced:** `build_fetch_tool(..., grant: FetchGrant | None = None)`.

- **Redirects are not followed under a grant.** The client is built with `follow_redirects=False`. A 3xx returns, in band, the `Location` it declined to follow and why — so the model can fetch it if that host is granted. Without a grant, `follow_redirects=True` stays exactly as it is; a human approving a fetch is present to see where it went.
- **The budget decrements only on a request that leaves the process.** `fetch` answers from the corpus and then the memo before any request (`fetch.py:226-241`); neither spends. Pin both.
- A grant-bound fetch whose budget is spent should not be reachable — the gate refuses first (Task 3). Decide what the tool does if called anyway, implement it, and say why in the report; do not leave it undefined.
- Everything else about `fetch` is unchanged: the scheme refusal, `MAX_BYTES`, `MAX_CHARS`, the citation header, the corpus and memo lookups, `PageMemo` retention.

- [ ] **Step 1: Write the failing tests.** Under a grant: a redirect is not followed and the response names the location; a successful network read spends one; a corpus hit spends nothing; a memo hit spends nothing; an error spends nothing. Without a grant: redirects still followed, nothing spends, behaviour identical.
- [ ] **Step 2: Prove them red.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green, plus every pre-existing test in the file.**
- [ ] **Step 5: Both ruff gates; commit by explicit path.**

---

### Task 6: An unanswerable approval is refused

**Files:** `research_team/interfaces/web/approvals.py`; tests alongside its existing tests

**Interfaces produced:** `WebApprovals` gains the registry and a timeout constant.

- An approval raised on a session the registry knows (`is_unattended`) waits a bounded time and is then **refused** — the same outcome the no-approvals-port build already produces (`deep_agent.py:481-490`). The turn continues on a rejection the model can read.
- **An unregistered session is untouched and waits forever.** Write the test whose only job is to fail if a timeout is ever applied to a human's session, and say that in its docstring.
- The timeout is a module constant with a named default, long enough that a browser answering promptly still succeeds. Justify the number in its docstring — say it is a guess and cheap to change, rather than implying it was measured.
- Use the same clock-injection style the codebase already uses for testable timing, so the test does not sleep.

- [ ] **Step 1: Write the failing tests.** A registered session's approval is refused after the bound; an unregistered session's is not bounded; a prompt answer still succeeds under a bound; the refusal's shape matches what the turn already handles.
- [ ] **Step 2: Prove them red.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green, plus the existing approvals tests.**
- [ ] **Step 5: Both ruff gates; commit by explicit path.**

---

### Task 7: Granting, plumbing, and all four gates

**Files:** `research_team/interfaces/web/app.py`, `research_team/application/research_supervisor.py`, `research_team/application/auto_research.py`, `research_team/composition.py`; the integration tests

- `NewRun` gains `fetch_hosts: list[str] = []` and `fetch_budget: int = 0`. **Half a grant is refused at the route** — hosts without budget, or budget without hosts — with a message naming the missing half. A person supplying one believed the other was implied.
- The grant travels: route → `ResearchSupervisor.start` → the `StartRun` callable alias (`research_supervisor.py:62-64`) → `composition.start_run` → `AutoResearchDriver.run` → the `StartRun` command → the event. **Widening that callable alias is unavoidable; note it in the commit message.**
- The driver **registers** the grant against the run's session when the run starts and **releases it in `_stop`**. Registration must happen from the folded state or the command — one source, not two — so the registry and the log cannot disagree.
- Sessions are registered even when nothing is granted (an empty grant), because Task 6's bounded wait keys off *being a run's session*, not off having hosts.
- **One `GrantRegistry`** in `composition.py`, passed to: `interrupt_config` (via the executor), the tools provider, `WebApprovals`, and the driver. Two instances would mean the gate and the tool disagreeing about the same grant — the silent-failure mode of this task, and the same shape as the shared-`PageMemo` and shared-`SearchAttempts` hazards in the two previous features.
- **No `AGENT_FETCH_HOSTS`.** A config default would be a standing grant to every run, which is the unscoped elevation this replaces.

- [ ] **Step 1: Write the failing integration tests.** A granted run's fetch to an allowed host succeeds without an approval; to a disallowed host it does not; the grant is on `AutoRunStarted` and on the folded state; the registry entry is gone after the run stops; a run started with no grant behaves exactly as today; half a grant is refused at the route naming the missing half.
- [ ] **Step 2: Prove them red.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: ALL FOUR GATES.** Run `uv run pytest` in the FOREGROUND. Paste actual output for each. One vitest process at a time.

```
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

Do not claim a gate passed without showing it. If one fails and you cannot fix it in scope, report BLOCKED with the real failure text.

- [ ] **Step 5: Commit by explicit path.**

---

## Self-Review

**Spec coverage.** §1 (gate, not policy) → Task 3. §2 (what a grant is, exact host matching) → Task 1. §3 (redirects) → Task 5. §4 (budget bounds the tool; `exhausted()` untouched) → Tasks 1, 5, and Task 2's explicit prohibition. §5 (recorded, cannot outlive the run) → Tasks 2 and 7; the "how the grant reaches the two places" subsection → Tasks 3, 4 and 7. §6 (a human grants at start) → Task 7. §7 (unanswerable approval) → Task 6. Every spec testing bullet maps to a named step above.

**Placeholders.** No task carries literal code, deliberately. The previous plan in this repo prescribed test bodies verbatim; every one of its placeholder fixture names turned out not to exist, costing three separate adaptations, and a reviewer noted that prescribed code weakens what red-green proves — it confirms "matches the brief" rather than independently-derived correctness. Each task here names the real files, the real constraint, and the invariants to pin, and requires the implementer to read the file's existing fixtures. Task 5 Step 3 carries an explicit open decision (what a spent grant-bound tool does if called directly) stated as a decision to make and record, not a gap to fill silently.

**Type consistency.** `FetchGrant.hosts` is `frozenset[str]` in memory and `list[str]` on the wire and the event, converted at the boundary in Task 7. `fetch_budget` is `int` everywhere. `GrantRegistry` keys are the session `UUID` throughout — never the run id, which no turn can see.

**Ordering hazard.** Tasks 1 and 2 are inert. Task 3 makes the gate consult grants that nothing creates yet, so it is testable only with a hand-built registry — that is expected, and its tests should build one directly. Task 7 is the first point anything real is granted, and the only task running all four gates. Six green tasks are not evidence the feature works.

**The two things most likely to go wrong, flagged for executors.** First, Task 7's single-registry requirement: two instances make the gate and the tool disagree, every unit test still passes, and a granted fetch either interrupts when it should not or is uncounted. Second, Task 3's fail-closed rule: if the URL argument cannot be read, the answer is "not covered". A predicate that returns "covered" on a parse failure is an authorization bypass, and it is the natural shape of a `try/except` written in a hurry.
