# Defects and unfinished decisions

Four items that are wrong, or undecided, in the tree today. They share no code
and no theme beyond that; they are batched because each is small and because a
list of known defects that stays a list is a list nobody trusts.

One item that appeared on the original list is already fixed and is recorded
here so the correction survives: **token counting no longer excludes tool-call
arguments.** `compaction.py`'s `_billable_text` counts tool-call names and
arguments alongside content, and the measurement that motivated it (224
counted tokens against roughly 2,600 real ones on a write-heavy session) now
survives as the justification in `_tokens`' docstring rather than as a
description of a bug. It landed in `c0128b0`. `docs/direction.md` still lists
it as open and is corrected as part of this work.

## 1. `SearchAttempts` is process-wide while claiming to be per-turn

### What is wrong

`research_team/infrastructure/agent/search.py`. Every docstring in the class
says "this turn". The object is not per-turn: `build_application`
(`composition.py:542`) constructs one `SearchAttempts` for the one `web_search`
tool the whole process shares, so two turns running concurrently — different
sessions, or an auto-research run alongside a web turn — share one counter.
One turn's run of empty searches can bound another turn's first search, and
either turn's boundary reset can clear the other's streak mid-turn.

The class docstring says all of this itself, which is the part that matters:
this is the one place in the codebase where something knowingly wrong is
tolerated in a shipped contract. The blast radius is genuinely small — nothing
durable depends on the count, and the failure modes are a spurious in-band
notice or a bound that fails to apply — but the cost of a class whose own
documentation retracts its stated contract is not measured in blast radius.

### Why the recorded blocker does not have to be paid

The docstring names the blocker as "the larger change of making the tool (and
its dependency on a single SearXNG client) rebuildable per turn", and
`BACKLOG.md` defers it on that basis. That framing is what has kept it
deferred, and it is wider than the problem.

What needs to be per-turn is the counter. The tool does not, and the SearXNG
client emphatically does not — rebuilding an `httpx.AsyncClient` per turn would
discard connection pooling to buy nothing. The counter is shared for one
reason: it is reachable from two places, the tool closure and
`SearchAttemptsMiddleware`, and the only thing both can currently hold is one
object.

### Design

`SearchAttempts` keeps its public surface — `record_empty()`, `reset()`,
`exhausted()` — and stops holding the count. It holds a `ContextVar` whose
value is a small mutable counter. `SearchAttemptsMiddleware.before_agent`
installs a fresh counter into the var before the turn's first model call. The
tool closure reads the var and mutates whatever it finds there.

Two concurrent turns are two asyncio tasks with two contexts, so they hold two
counters. The tool and the client are still built once.

The counter in the var is a **mutable object rather than an integer**, and that
is load-bearing rather than incidental. A child task copies its parent's
context at spawn: a value set before the spawn is visible in the child, but a
`set()` performed *inside* the child is invisible to the parent and to
siblings. Storing a mutable object means the tool mutates state the middleware
can still see, whether or not langgraph runs the tool call in the same task as
`before_agent`.

A default is needed for the case where no middleware has run — a
`build_search_tool` caller in a test, or any path that builds the tool without
the agent around it. The var's default is a counter that behaves exactly like
today's fresh instance, so an unwired tool is unbounded-per-process rather than
raising, which is the current behaviour for the same case.

### What decides whether this works

Whether langgraph installs a fresh context per tool call. If it does,
contextvars cannot carry the counter and this design is wrong.

This is settled by a test, not by reading langgraph: two turns run
concurrently through the real middleware and the real tool, and each must see
only its own streak. The test is proved red against the shared instance before
it is trusted green.

**If it fails, stop and report rather than substituting an approach.** The
fallback is keying counters off a run identifier already present in middleware
state, which is a different design with a different cost, and swapping to it
silently would be the more expensive mistake.

### Scope

Every docstring in `SearchAttempts` that says "this turn" becomes true. The
paragraph admitting the contract is false is deleted and replaced with a
shorter one recording what the mechanism depends on — the mutable-object-in-a-
var point above, because that is the thing a future reader would otherwise
"simplify" into an integer and break. The `BACKLOG.md` deferral is removed.

## 2. Search exposes none of SearXNG's `engines`, `categories` or `time_range`

### What is wrong

Not a defect; a capability gap, included because it lives in the file item 1 is
already open in. `build_search_tool` sends only `q` and `format`. For an agent
choosing between a general query and a scholarly one, or between anything and
anything published this year, that is a missing capability rather than a
deliberate simplification — `langchain-community`'s SearXNG wrapper, an
unmaintained package, is more configurable here than this is.

### Design

Three optional parameters — `engines`, `categories`, `time_range` — on both
`build_search_tool`, where they set an instance default, and on the `web_search`
tool signature, where a call overrides it. Unset parameters are omitted from
the request rather than sent empty, because SearXNG treats an empty
`time_range` and an absent one differently.

The tool docstring is what the model reads, so it must say what the parameters
are for in the model's terms and not merely name them.

### The part that is not plumbing

**The parameters must enter the recall key.**

`Recall` currently keys a search on `query_key(query)` alone. Add parameters
without touching that and the same words with `time_range="year"` hit a memo
stored for the unrestricted search, and the model is handed — labelled as
recalled, and therefore trusted — an answer to a question it did not ask.

That is precisely the failure `recall.py`'s normalization rule exists to
prevent: fold only where the upstream is already insensitive. SearXNG is not
insensitive to these parameters; they change what it returns, which is the
entire reason for adding them.

So the key becomes the query together with the parameters that change the
answer. A test asserts that two searches differing only in `time_range` do not
share a memo entry, and it is proved red before the key changes.

## 3. `checks.py` has one line of domain coupling left

### What is wrong

`ArtifactType` appears five times in 2013 lines of
`research_team/application/checks.py`, and three of those are inside error
strings. The one genuine coupling is `_criterion_doc_authored`
(`checks.py:1838`), which selects `TypeFilter(artifact_type=ArtifactType.CRITERION_DOCUMENT)`
directly. Every other check routes its selection through a `TypeFilter` supplied
by its binding.

### Why it is worth a change this small

The deliverable is not the line. It is that "shared checks know no domain"
becomes a property a test enforces rather than one a reader observes. That rule
is what keeps the check library from silently becoming three libraries, one per
methodology, and a rule with one live exception is a rule that erodes at the
next exception.

### Design

`CriterionDocAuthoredParams` grows a `TypeFilter` field defaulting to
`CRITERION_DOCUMENT`; the check selects through it; `hybrid.py:279`'s binding
passes it explicitly so the one live caller states its own vocabulary rather
than inheriting it.

The default is what keeps this cheap: the four existing tests
(`test_checks.py:1206`, `:1230`, `:1249`, `:1260`) pass unchanged, so the
change is provably behaviour-preserving rather than argued to be.

Then a test asserting that `ArtifactType` appears in `checks.py` only inside
string literals. It belongs with the other structural rules in
`tests/test_architecture.py`, alongside the existing import-direction and
no-model-in-a-check rules, because it is the same kind of claim. It is proved
red by reverting the selection.

## 4. The unreadable-page ceiling is undecided

### What is unfinished

`fetch.py`'s `UNREADABLE` path is a dead end for any JS-rendered page.
`FETCH_PROMPT` already tells the model an app shell will come back empty
however many times it asks, which is an honest answer. What is missing is that
nobody decided it: no headless browser was considered and refused, one was
simply never added.

The distinction matters because a default and a decision fail differently. The
next person to meet an app shell re-derives the whole argument, and may well
add Playwright on the strength of one frustrating afternoon.

### The decision

**Accept the ceiling. No code change.**

The reasoning, recorded where it will be found:

- A headless browser is a large dependency — a browser binary, a download step
  in CI, and a resource profile unlike anything else this process runs.
- It introduces a class of failure the current fetch path cannot produce at
  all: render timeouts, anti-bot challenges, and pages that succeed slowly
  enough to matter. Every one of those is a new thing that can go wrong on the
  way to a citation.
- The honest answer is already given. `FETCH_PROMPT` tells the model the truth
  and the model can record a gap, which is the behaviour the coverage machinery
  wants from an unreachable source anyway.

### Scope

A paragraph on `UNREADABLE` (`fetch.py:49`) recording that the fallback was
refused and why, and a `BACKLOG.md` entry in the style of B11 and B21 — chosen
deliberately, cost stated, and **naming its own trigger for revisiting**. The
trigger is a corpus the project actually wants being behind an app shell.
Without a named trigger the entry is a rationalisation; with one it is a
decision that knows what would overturn it.

## Verification

All four gates, because three of four is not passing:

```
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

The frontend is untouched and its gate runs anyway. The two ruff commands cover
the whole repository including tests, which is where this kind of change
usually breaks CI.

`docs/direction.md`'s stale token-counting entry is corrected in the same
change. A known-wrong defect list sitting beside the commit that fixes its
neighbours is worse than no list.

## Out of scope

Named because each was in front of us while working and left alone
deliberately:

- Anything from `docs/direction.md`'s "worth building" section.
- `B22` (`self_review_separation` bound like an option) and `B38` (four
  `matrix_density` bindings with no axes), both of which live in the files item
  3 touches. Each changes the contract between presets and the engine, which is
  a decision to make deliberately rather than inside a defect round.
- A Playwright fallback, refused above rather than deferred.
