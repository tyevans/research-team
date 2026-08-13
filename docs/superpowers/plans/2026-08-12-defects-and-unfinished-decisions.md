# Defects and Unfinished Decisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `SearchAttempts` per-turn in truth as well as in its docstrings; expose SearXNG's `engines` / `categories` / `time_range` without corrupting the recall memo; remove the last line of domain coupling from `checks.py` and make its absence enforceable; and decide the unreadable-page ceiling rather than leaving it defaulted.

**Architecture:** Four independent changes sharing no state. Tasks 1 and 2 are the same file and are sequenced. Task 3 is untouched by either. Task 4 is prose. Nothing here adds a dependency, an event, a read model or a migration.

**Tech Stack:** Python 3.13, `uv`, pytest, langchain agent middleware, httpx, pydantic. No new dependencies.

## Global Constraints

- **`Recall`'s normalization rule is not relaxed.** Fold only where the upstream is already insensitive; never stem, sort or embed. Task 2 adds to the key; it must never merge two questions.
- **Do not run the full test suite.** Run only the test files your task touches. Both ruff gates run over the WHOLE repository and must pass before every commit. The integrator runs the full suite and the frontend gate once.
- **Do not run two `vitest` processes at once.** No task here touches the frontend; if you find yourself about to run one, stop — you are outside your task.
- **Prove every test red before trusting it green,** and paste the actual failure output into your report. A test that has never failed is not evidence. If a test would pass with the change reverted, say so in its docstring rather than leaving it as reassurance.
- **House style:** comments and docstrings carry the REASONING and state costs and trade-offs, not restatement of the code. Name what a test would fail on. Say when something was measured rather than reasoned. A comment that restates the code is worse than none.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Stage by explicit path. NEVER `git add -A`** — this repository is worked in concurrently.
- **Do not use bare `git stash` / `git stash pop`** — the stack is shared across worktrees.
- **Do not fix B22 or B38.** Both live in the files Task 3 touches. Both change the contract between presets and the engine. Out of scope, deliberately.

## File Structure

| File | Responsibility |
|---|---|
| `research_team/infrastructure/agent/search.py` | `SearchAttempts` becomes context-scoped (T1); three SearXNG parameters (T2) |
| `research_team/infrastructure/agent/search_middleware.py` | Installs a fresh counter per turn (T1) |
| `research_team/infrastructure/agent/recall.py` | Search memo key admits the parameters that change the answer (T2) |
| `research_team/application/checks.py` | `_criterion_doc_authored` selects through a supplied `TypeFilter` (T3) |
| `research_team/workflows/hybrid.py` | The one live binding states its own vocabulary (T3) |
| `tests/test_architecture.py` | `ArtifactType` appears in `checks.py` only inside string literals (T3) |
| `research_team/infrastructure/agent/fetch.py` | `UNREADABLE` records the refused fallback (T4) |
| `BACKLOG.md` | T1's deferral removed; T4's decision added |

**Ordering note.** Tasks 1, 3 and 4 are independent and run in parallel. Task 2 follows Task 1 in the same file. Task 5 is integration and is the only task that runs all four gates.

---

### Task 1: `SearchAttempts` is per-turn in truth

**Files:** `research_team/infrastructure/agent/search.py`, `research_team/infrastructure/agent/search_middleware.py`; tests `tests/infrastructure/test_search.py` (or wherever the existing 25 search tests live) and the middleware's test file.

**Interfaces produced:** `SearchAttempts` keeps `record_empty() -> int`, `reset() -> None`, `exhausted() -> bool` unchanged in signature and meaning. Add whatever the middleware needs to install a fresh counter — a method, not attribute poking.

**Design notes the implementer must honour:**

- The count moves into a `contextvars.ContextVar` whose value is a **mutable counter object, never a bare `int`.** This is load-bearing. A child task copies its parent's context at spawn: a value set before the spawn is visible in the child, but a `set()` performed inside the child is invisible to the parent and to siblings. A mutable object means the tool mutates state the middleware can still see, whether or not langgraph runs the tool call in the same task as `before_agent`. Say this in a comment — the next reader will otherwise "simplify" it to an int and break it silently.
- The var needs a default for the case where no middleware has run: a `build_search_tool` caller in a test, or any path building the tool without the agent around it. The default must behave like today's fresh instance — unbounded-per-process, not raising. That is the current behaviour for that case and this task is not the place to change it.
- The tool and the `httpx.AsyncClient` are still built **once**. Do not make either per-turn. Rebuilding the client would discard connection pooling to buy nothing, and the recorded blocker ("make the tool and its client rebuildable per turn") is wider than the problem.
- Every docstring in `SearchAttempts` that says "this turn" becomes true. **Delete the paragraph beginning "This instance is process-wide, not per-turn"** and replace it with a shorter one recording what the mechanism depends on.
- Remove the corresponding deferral from `BACKLOG.md`. CLAUDE.md: closed entries are deleted, and if tracked code cites one by name, say where its reasoning went. `search.py`'s docstring currently ends "See BACKLOG.md" — that reference goes with it.

**The test that decides whether this design is correct:** two turns running **concurrently** through the real middleware and the real tool, each seeing only its own streak. Everything else in this task is bookkeeping; this is the claim.

- [ ] **Step 1: Write the failing concurrency test first,** before any implementation. Two concurrent turns, one exhausting its streak, the other asserting it is unbounded. Also cover: a fresh turn starts at zero; a non-empty result resets; `exhausted()` at exactly `MAX_EMPTY_SEARCHES`; an unwired tool (no middleware) still works.
- [ ] **Step 2: Run it against the current shared instance and paste the actual failure.** It must fail for the right reason — one turn bounding the other — not on a fixture error.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the search and middleware test files green.** Do not run the full suite.
- [ ] **Step 5: `uv run ruff check .`, `uv run ruff format --check .`, commit by explicit path.**

**STOP CONDITION.** If the concurrency test cannot be made to pass with contextvars — because langgraph installs a fresh context per tool call — **stop and report. Do not substitute the fallback design.** The fallback is keying counters off a run identifier in middleware state; it has a different cost and swapping to it silently is the more expensive mistake. Report what you observed, with the failure output.

---

### Task 2: SearXNG `engines`, `categories`, `time_range`

**Depends on Task 1** (same file). Start only when Task 1 is committed.

**Files:** `research_team/infrastructure/agent/search.py`, `research_team/infrastructure/agent/recall.py`; tests for both.

**Interfaces produced:** `build_search_tool(..., engines=None, categories=None, time_range=None)` setting instance defaults, and the same three as optional arguments on the `web_search` tool signature, where a call overrides the default.

**Design notes the implementer must honour:**

- **Unset parameters are omitted from the request, not sent empty.** SearXNG treats an empty `time_range` and an absent one differently.
- The tool docstring is what the model reads. Say what the parameters are *for* in the model's terms — when a scholarly category or a recency bound is the right reach — not merely that they exist.
- **The parameters must enter the recall key.** This is the part that is not plumbing. `Recall` currently keys a search on `query_key(query)` alone. Add parameters without touching that and the same words with `time_range="year"` hit the memo stored for the unrestricted search, and the model is handed — labelled as recalled, and therefore trusted — an answer to a question it did not ask. That is exactly the failure `recall.py`'s normalization rule exists to prevent: SearXNG is *not* insensitive to these parameters, which is the whole reason for adding them.
- Keep `query_key`'s existing normalization for the query itself. You are extending the key, not replacing the rule.
- `format_recalled` names the query a memo was stored for. Consider whether it should now also name parameters that differ; if you decide not to, say why in a comment rather than leaving it unexamined.

- [ ] **Step 1: Write the failing tests.** At minimum: two searches differing only in `time_range` do not share a memo entry; likewise `engines` and `categories`; unset parameters are absent from the request params, not empty; a per-call argument overrides the instance default; the existing no-parameter path is byte-for-byte unchanged in what it sends.
- [ ] **Step 2: Run them and paste the actual failure.** The memo-collision test must fail by *returning the wrong recalled answer*, which is the bug — not by raising.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the search and recall test files green.** Do not run the full suite.
- [ ] **Step 5: `uv run ruff check .`, `uv run ruff format --check .`, commit by explicit path.**

---

### Task 3: `checks.py` knows no domain, enforceably

**Files:** `research_team/application/checks.py`, `research_team/workflows/hybrid.py`, `tests/test_architecture.py`; existing tests in `tests/application/test_checks.py`.

**Design notes the implementer must honour:**

- `CriterionDocAuthoredParams` grows a `TypeFilter` field **defaulting to `CRITERION_DOCUMENT`**; `_criterion_doc_authored` (`checks.py:1838`) selects through it; `hybrid.py:279`'s binding passes it explicitly so the one live caller states its own vocabulary rather than inheriting it.
- The default is what keeps this cheap. The four existing tests (`test_checks.py:1206`, `:1230`, `:1249`, `:1260`) must pass **unchanged** — that is what makes the change provably behaviour-preserving rather than argued to be. If you find yourself editing them, stop and reconsider the design.
- The deliverable is not the line; it is that "shared checks know no domain" becomes a property a test enforces rather than one a reader observes. A rule with one live exception erodes at the next exception.
- The new test belongs in `tests/test_architecture.py` beside the existing import-direction and no-model-in-a-check rules, because it is the same kind of claim. It must assert `ArtifactType` appears in `checks.py` **only inside string literals** — three of the five current occurrences are in error strings and are fine. Parse rather than grep if grepping cannot make that distinction honestly; a test that would pass on a commented-out occurrence is not the test described.
- Do not touch B22 or B38.

- [ ] **Step 1: Write the failing architecture test.**
- [ ] **Step 2: Run it against the current code and paste the actual failure.**
- [ ] **Step 3: Implement the `TypeFilter` parameter and the `hybrid.py` binding.**
- [ ] **Step 4: Run `tests/application/test_checks.py`, `tests/application/test_stage_exit.py`, `tests/domain/test_workflow.py`, `tests/application/test_preset_gates.py` and `tests/test_architecture.py` green.** Confirm in your report that the four cited tests were not edited.
- [ ] **Step 5: `uv run ruff check .`, `uv run ruff format --check .`, commit by explicit path.**

---

### Task 4: Decide the unreadable-page ceiling

**Files:** `research_team/infrastructure/agent/fetch.py` (the `UNREADABLE` constant, line 49), `BACKLOG.md`. No behaviour change, no test.

**Design notes:**

- A paragraph on `UNREADABLE` recording that a headless-browser fallback was **considered and refused**, with the reasoning: a browser binary is a large dependency with a CI download step and a resource profile unlike anything else this process runs; it introduces failures the current path cannot produce at all (render timeouts, anti-bot challenges, pages that succeed slowly enough to matter), each of which is a new thing that can go wrong on the way to a citation; and `FETCH_PROMPT` already tells the model the truth, so the model can record a gap — which is what the coverage machinery wants from an unreachable source anyway.
- A `BACKLOG.md` entry in the style of B11 and B21: chosen deliberately, cost stated, and **naming its own trigger for revisiting.** The trigger is a corpus the project actually wants being behind an app shell. Without a named trigger the entry is a rationalisation; with one it is a decision that knows what would overturn it.
- The distinction being recorded is that a default and a decision fail differently. The next person to meet an app shell should find an argument, not a silence.

- [ ] **Step 1: Write both passages.**
- [ ] **Step 2: `uv run ruff check .`, `uv run ruff format --check .`, commit by explicit path.**

---

### Task 5: Integration

**Integrator only.** Not a subagent task.

- [ ] Correct `docs/direction.md`'s token-counting entry — it is already fixed (`c0128b0`); `_billable_text` counts tool-call arguments and the 224-vs-2,600 measurement survives as justification, not as a bug report.
- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run pytest` — the whole suite, once, on a quiet machine. A failure under load is not evidence until it reproduces alone; re-run a failure in isolation before investigating it, and then re-run the whole suite, because some failures only appear in company.
- [ ] `cd frontend && npm run verify` — untouched by this work and run anyway. Three of four gates is not passing.
- [ ] Open the PR.

---

## Corrections found in execution

Appended rather than edited in place. The tasks above are left as they were
written, because a plan that is quietly repaired loses the evidence that it was
wrong, and both of these were worth knowing.

**Task 1's "the var's default" is not implementable under this repo's ruff
configuration.** `B039` rejects a mutable `ContextVar` default, and it is right
in general: a default is evaluated once and shared across every context, which
is a bug nearly everywhere and was precisely the intent here. The committed
resolution keeps the semantics exactly — a fallback counter held as an instance
field and consulted by `_current()` when the var is unset, which is the same
single shared object a default would have handed every context. Read "a
fallback consulted when the var is unset" wherever the task says "the var's
default".

The integrator initially directed a `# noqa: B039` instead and was wrong. The
objection given was that the alternative would install a counter lazily on
first use, and that a lazy `.set()` inside a child task is invisible to the
parent and its siblings — true, and not what was built. `.set()` is called in
exactly one place, `begin_turn()`; the unwired path never sets the var at all.
With behaviour identical either way, a named `_unwired` field beats a standing
claim that a lint rule does not apply, which a future reader would have to
re-derive to trust.

**Task 3's test as specified could not pass on any correct version of the
file.** The plan asks that `ArtifactType` appear in `checks.py` "only inside
string literals", on the strength of a count that was wrong. The import and the
`Artifact.artifact_type` / `TypeFilter.artifact_type` annotations are
legitimate non-string uses that commit to no methodology, and forbidding them
would leave the check library unable to describe the filter it is handed. The
property that is actually true after the fix and false before it is narrower:
**`checks.py` names no *member* of `ArtifactType`.** The intent — shared checks
know no domain — is unchanged and is now enforced; only the mechanical wording
was unsatisfiable.
