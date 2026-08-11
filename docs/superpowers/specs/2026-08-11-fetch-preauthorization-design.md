# Letting a run fetch, on a leash

## The problem

An autonomous research run cannot read a page it does not already hold. `fetch`
floors at `ask` (`application/autonomy.py:65`), and an unattended loop that
reaches an approval has no good outcome: with no approvals port wired the call
is auto-rejected (`infrastructure/agent/deep_agent.py:481-490`), and with the
web port wired it **blocks on a future with no timeout**
(`interfaces/web/approvals.py:83`). So a run either cannot fetch or hangs
trying.

The hang is worse than B24 records. `ResearchSupervisor.cancel` sets a flag read
only between rounds (`application/auto_research.py:191-192`,
`research_supervisor.py:181-198`), so a run parked on an approval **cannot be
cancelled at all**, and `stop_all` awaits the task and hangs with it
(`research_supervisor.py:220-236`).

What stands in for a solution today is a claim rather than a control.
`read_only` is computed once from the live policy
(`composition.py:1114`) and **never read by anything**; `fetch` is registered
unconditionally (`composition.py:505`) and nothing prevents the model calling
it. The only way to make a run able to fetch is to set the instance policy to
`auto`, which makes **every** run on the instance able to fetch anything,
forever, unscoped and uncounted.

B24 names both traps to avoid:

> Not a blanket "N auto-approvals", which is `auto` with a counter: the count is
> not what makes an approval meaningful, the scope is. And not the loop lowering
> `TOOL_FLOORS` itself, ever -- a loop that can edit its own permissions makes
> the floors advisory for everything else too.

## What this builds

A **pre-authorization**: a person, when starting a run, may grant it permission
to fetch from named hosts, at most N times. The grant is recorded on the run's
stream, enforced at the approval gate, and cannot outlive the run.

`TOOL_FLOORS` and `AutonomyPolicy` are not modified, not read differently, and
not written by anything in this design.

## 1. The grant is consulted at the gate, not applied to the policy

`_gate_for` builds a `when(request) -> bool` predicate per gated tool that
returns `policy.level_for(tool) != "auto"` and **ignores the request**
(`infrastructure/agent/approval.py:39-44`). `interrupt_config(self._policy)` is
rebuilt on every pass of the resume loop, inside `_invoke`, **with the session
in scope** (`deep_agent.py:359-364`).

That is the seam. `when` becomes: interrupt unless the policy already says
`auto`, **or** a grant covers this specific call. A covered fetch never reaches
an approval, so it never hangs and never auto-rejects. An uncovered one behaves
exactly as it does today.

**Rejected — raising the run's autonomy level.** Setting `fetch` to `auto` for
the run is the obvious implementation and is precisely what B24 forbids.
`AutonomyPolicy` is one object per process (`composition.py:467`), with a
comment saying a second one "would let a run cross gates the operator had not
relaxed" (`:1128-1133`). There is no per-session policy, and inventing one to
hold a temporary elevation would put a second, mutable source of truth beside
the operator's.

**Rejected — a counted auto-approval in `_decide`.** Answering the approval
automatically, N times, is "auto with a counter" by B24's own words. It also
writes `RecordToolDecision(decided_by=...)` entries claiming a decision nobody
made.

**Chosen — the gate asks whether this call is covered.** Scope is evaluated per
call, against the arguments, which is what makes it a scope rather than a
count.

## 2. What a grant is, and what covers a call

```
@dataclass(frozen=True)
class FetchGrant:
    run_id: UUID
    hosts: frozenset[str]   # exact, lowercased, no wildcards
    budget: int             # total fetches that may leave the process
```

A call is covered when the tool is `fetch`, the grant's budget is not spent, and
the request URL's host is in `hosts`. Host comparison is exact after
lowercasing — `urlsplit(url).hostname`, which already lowercases and strips any
`user:pass@` (`recall.py:95`).

**No wildcards, no suffix matching.** `*.example.com` reads as a small
convenience and is a large hole: suffix matching invites `evil-example.com`
against a naive check and `example.com.attacker.net` against a careless one, and
getting it right means public-suffix knowledge this project does not have and
should not acquire for this. A person granting three hosts can name three hosts.

**Subdomains are separate hosts.** `example.com` does not cover
`www.example.com`. This will annoy someone, and the alternative is the wildcard
above.

## 3. Redirects are not followed under a grant

`fetch` sets `follow_redirects=True` (`fetch.py:242`) and **nothing inspects the
redirect chain or the final URL**. So an allowlisted URL that answers `302
Location: https://anywhere.example` is fetched from a host nobody granted, and
the allowlist is decorative. This is the one place where the obvious
implementation is not merely weaker but actively false.

Under a grant, `fetch` builds its client with `follow_redirects=False`. A
redirect returns, in band, the location it wanted and the fact that it was not
followed. If the target host is also granted, the model can fetch it — one more
call, one more budget decrement, checked like any other.

**Rejected — following redirects and validating afterwards.** By the time
`response.url` can be read, the request has already been made to the
disallowed host: headers sent, presence disclosed. Validating after the fact
records a violation instead of preventing one.

**Rejected — following redirects while checking each hop.** Correct in
principle; httpx offers no per-hop hook without reimplementing redirect handling
here, and a hand-rolled redirect loop in a fetch tool is a larger and more
dangerous piece of code than the problem justifies.

Ungranted `fetch` keeps `follow_redirects=True`, unchanged. This is deliberately
asymmetric: a human approving a fetch is present to see where it went, and
changing that path would alter behaviour this spec has no reason to touch.

## 4. Spending bounds the tool, not the run

The fetch budget is **not** part of `Budget` and **not** consulted by
`exhausted()`.

`exhausted()` is a pure fold of the run's own stream
(`domain/auto_research.py:274-291`), and its docstring makes that a property
worth keeping: "the driver never decides for itself when to stop: it asks, and
the answer is a fold of the log". A per-fetch counter cannot be folded from the
log unless every fetch is an event on the run's stream — and the driver holds
one `run` aggregate across the entire loop, saving only between rounds
(`application/auto_research.py:171`, `:182`, `:207`), so a mid-turn append from
a tool would write from a version behind the copy the driver still holds.

So the budget lives on the grant object, is decremented in the tool, and stops
being a run-level concept entirely. **The run stops when its rounds run out; the
grant stops when its fetches run out. Neither ends the other.** A run whose
grant is spent keeps working over the corpus, which is what it did before this
change.

A spent grant makes `when` return `True` again, so the next fetch reaches the
gate and is refused exactly as an ungranted one is. The failure mode of running
out is the behaviour that exists today, not a new one.

**Cache hits do not spend.** `fetch` answers from the corpus and then the memo
before any request (`fetch.py:226-241`). The budget bounds *requests that leave
the process*, which is what a person granting it is deciding about.

## 5. The grant is recorded, and cannot outlive the run

`AutoRunStarted` gains `fetch_hosts: list[str]` and `fetch_budget: int`,
defaulting to `[]` and `0` — a run granted nothing is the existing behaviour and
the existing payload shape. `AutoRunState` carries them too, so "what was this
run allowed to do?" is answerable from a fold, which `autonomy_snapshot` is not
(`domain/auto_research.py:396-404` never reads it).

Enforcement uses a process-local registry keyed by session id — the run has its
own session (`app.py:1195`), so a session-keyed grant is run-scoped in practice,
and the session is the only identity that reaches a turn
(`deep_agent.py:417-435`). The registry entry is created when the run starts,
from the event, and removed in `_stop`.

### How the grant reaches the two places that need it

Two things must know about a grant, and neither can look it up on its own: the
gate predicate, which decides whether to interrupt, and `fetch` itself, which
must disable redirects (§3) and decrement the budget (§4). The base `fetch` is
built once for the whole process (`composition.py:505`) and its closure holds no
identity at all (`fetch.py:194-293`).

The executor already re-resolves both per turn, with the session in hand:
`_resolved_middleware(session)` and `_resolved_tools(session)`
(`deep_agent.py:417-454`), asked again on **every pass of the resume loop**
(`:357-358`), and `interrupt_config` is rebuilt in the same place (`:364`). So
both consult the registry with `session.aggregate_id`:

- `interrupt_config` gains the session, so `when` can ask whether this call is
  covered.
- `tools_provider` returns a grant-bound `fetch` that shadows the base one by
  name, which is the mechanism `KnowledgeAttachment._compose` already uses for
  the corpus-aware `fetch` (`application/knowledge_attachment.py:19-39`).

A session with no grant gets today's tool and today's predicate, by the same
lookup returning `None`. **The ungranted path must be byte-for-byte the
behaviour that exists now**, because it is every path except an explicitly
granted run.

**Rejected — passing the grant as a tool argument.** The model would then name
its own authorization, which is not an authorization.

**Process death revokes every grant, for free.** A registry that lives in memory
cannot outlive the process, and an abandoned run — one whose stream has no stop
event, which `research_supervisor.py:18-20` says is deliberately never
reconstructed — therefore has no grant when the process comes back. **The one
case the log cannot describe is the one the in-memory design handles
correctly**, which is the argument for the registry being memory rather than a
projection.

**Rejected — deriving the grant from the log at fetch time.** It would make the
grant survive a restart, which is exactly wrong: the run it belonged to is gone
and nothing will stop it.

## 6. Granting is a human act, at the moment of starting a run

`NewRun` (`interfaces/web/app.py:243-273`) gains `fetch_hosts: list[str]` and
`fetch_budget: int`. The REPL's `/research` gains nothing; a person at a
terminal can answer approvals, which is the mechanism they already have.

A grant with hosts and no budget, or a budget and no hosts, is refused at the
route with a message naming which half is missing. Half a grant is a
misunderstanding, and the half that is present suggests the person believed the
other half was implied.

**No configuration default.** There is no `AGENT_FETCH_HOSTS`. A default
allowlist would be a standing grant to every run on the instance, which is the
unscoped elevation this spec exists to replace, arriving through the config file
instead of the policy. Every grant is named by a person, per run.

## What this does not do

**Nothing about the approval deadlock itself.** A run whose model calls `fetch`
outside its grant still parks on `WebApprovals` forever, and still cannot be
cancelled because the flag is read between rounds. This spec makes the common
case not reach the gate; it does not fix the gate. That is a real bug, it is
now written down, and it belongs to whoever fixes cancellation.

**No enforcement of `read_only`.** It stays a recorded claim. Making it a
control is a separate change and would collide with this one.

**No per-host budgets, no time limits, no rate limiting.** One count for the
whole grant. A person who wants two hosts bounded separately can run twice.

**No wildcards, ever, is not claimed** — only that this does not add them. If
someone later needs them, they need public-suffix handling and a spec that
argues for it.

**Nothing for the REPL.** A terminal run's approvals work.

**No audit of what was actually fetched.** The grant is recorded; individual
fetches are not events, per §4. What a run read is visible only as corpus
documents, which is where it was already visible.

## Testing

- A fetch to a granted host, within budget, does not interrupt.
- A fetch to an ungranted host interrupts, and is refused exactly as today.
- Host matching is exact: `example.com` does not cover `www.example.com`,
  `evil-example.com`, or `example.com.attacker.net`.
- Host comparison is case-insensitive and ignores `user:pass@`.
- A grant with a spent budget interrupts — the tool stops being covered rather
  than erroring.
- Budget decrements only on a request that leaves the process; a corpus hit and
  a memo hit do not spend.
- Under a grant, a redirect is not followed, and the response names the location
  it declined to follow.
- Without a grant, redirects are still followed — the existing behaviour is
  untouched.
- `TOOL_FLOORS` and `AutonomyPolicy` are unchanged by everything above: a test
  that fails if the grant is ever implemented by elevating a level.
- `exhausted()` is unchanged, and a spent fetch budget does not stop the run.
- The grant appears on `AutoRunStarted` and on the folded `AutoRunState`.
- A run started with no grant behaves exactly as it does today, with `[]` and
  `0` on the event.
- Half a grant — hosts without budget, or budget without hosts — is refused at
  the route, naming the missing half.
- The registry entry is gone after the run stops.
- A grant belonging to one session does not cover a fetch from another session.
