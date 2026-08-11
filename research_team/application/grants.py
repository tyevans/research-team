"""Pre-authorization for `fetch`: what a run may reach, and how many times.

`fetch` floors at `ask` (composition.py) so that a person sees every network
call an agent makes. An unattended run has nobody to answer that prompt, so it
either auto-rejects or hangs forever -- neither of which is a run that can do
research. A `FetchGrant` is the way a person authorizes a bounded slice of
that in advance: named hosts, a fixed number of requests, nothing else.

`covers()` is the authorization check `fetch`'s gate and tool both consult, so
it is written to answer "not covered" on every input it is unsure about,
following the totality argument `normalize_url` makes for the same reason
(`infrastructure/agent/recall.py:84-90`): both take text a model wrote, and a
string too malformed to parse should cost a redundant refusal, not a raised
exception that ends the turn.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID


@dataclass(frozen=True)
class FetchGrant:
    """What one run was authorized to fetch, and how much of it is left.

    `hosts` matches exactly, after lowercasing both sides, against
    `urlsplit(url).hostname` -- no wildcards, no suffix matching. `example.com`
    does not cover `www.example.com`, `evil-example.com`, or
    `example.com.attacker.net`; getting suffix matching right needs
    public-suffix knowledge this project does not have, and a person granting
    three hosts can name three hosts. Exactness is not normalization: a
    trailing root dot (`example.com.`) and an IDN A-label/U-label pair
    (`xn--...` vs. its Unicode form) are, to a browser, the same host as their
    plain spelling, but neither side is folded here, so both fail closed --
    the grantor's spelling is the only one that matches, which is a false
    refusal a person can retype, not a false grant nobody would notice.

    `hosts` is lowercased in `__post_init__`, not just the URL side in
    `covers()`. `hosts` arrives from `NewRun.fetch_hosts` -- strings out of an
    HTTP request body, so `Example.COM` is a spelling a person will actually
    type. Comparing an unlowered stored host against a lowered URL host fails
    every match silently: the grant looks set and authorizes nothing, which is
    worse than an error because nothing says so. Not stripped of whitespace,
    deliberately: a host with leading or trailing space is not a value this
    class should guess the meaning of, and guessing wrong here means guessing
    which host was actually meant.

    The dataclass is frozen because a grant is what a person decided, not
    something a tool call should be able to rewrite -- but a budget that never
    changed would not bound anything. `_remaining` is a single-element list
    used as a mutable cell so the mutation is confined to one field with an
    obvious name, rather than achieved by dropping `frozen=True` and trusting
    every future caller not to reassign `budget` or `hosts`. `spend()` is the
    only thing that touches it; `covers()` only reads it.

    `_reserved` is a second mutable cell, added to close a real over-spend a
    security review reproduced (task-5-review.md): `fetch`'s gate evaluates
    `covers()` for *every* call in one assistant message before any of them
    runs (`HumanInTheLoopMiddleware.after_model` iterates the whole message
    synchronously), and `langgraph`'s `ToolNode` then runs all the calls it let
    through with `asyncio.gather`. So N calls in one message, all covered
    under the same unspent budget, all pass the gate, and all N leave the
    process before any of their `spend()`s lands -- ten requests on a budget
    of one, confirmed by running it. `reserve()` is what closes the gap: the
    gate claims a unit *before* deciding not to interrupt, so the second call
    in a batch sees the first call's claim and is refused (interrupted) rather
    than also waved through.

    **`_reserved` is a `set[str]` of tool-call ids, not a count.** A count was
    the first version of this and a whole-branch review caught what it
    missed, by executing it: `interrupt()` raises `GraphInterrupt`, and on
    `Command(resume=...)` langgraph re-executes `after_model` from the top --
    so the gate calls `reserve()` a *second* time for every covered call in a
    message that also contains an interrupting one. A plain counter has no
    way to tell "this call already claimed" from "a new call wants to claim",
    so it double-claimed, which at low remaining budget flipped an already-
    admitted call to refused on the resume pass -- one decision came back for
    two now-hanging calls, and langchain raised `ValueError`. Keying by
    `tool_call["id"]` (already read by `_covered` in `approval.py`) makes
    `reserve()` idempotent per call: re-evaluating an id already in the set
    re-answers `True` without claiming a second unit. `covers()` is
    deliberately left reading only `_remaining`, not `_remaining - reserved`,
    so `fetch.py`'s existing `covers()`-then-`spend()` pair (unit-tested
    directly, with no gate in the loop) keeps meaning exactly what it always
    meant: `spend()` still floors against the real budget and still refuses
    to spend past zero, unaffected by whether a reservation happens to be
    outstanding.

    **Every claim must be released, not just spent.** The same review found
    that "an occasional leak is fine because it only ever lowers the ceiling"
    understated how often the leak fires: a claim taken at the gate is left
    stuck by *every* ordinary path that answers without a network read --
    a corpus hit, a memo hit, an `httpx` error, an HTTP error status -- not
    only the resume-reservation case above, because none of those call
    `spend()`. In a research run over a growing corpus, cache hits are the
    common case, not the exception, so a grant of N could reach zero
    admissible claims after a handful of real requests -- and the floor of
    that erosion was the crash above, not graceful degradation. So `fetch.py`
    now calls `release(call_id)` in a `finally` that covers every return path,
    whether or not `spend()` ran; `spend()` also releases the id it redeemed,
    and `release()` is a plain `set.discard`, so calling it after `spend()`
    already removed the id is a harmless no-op. What is still true, and now
    actually holds: a claim can delay a future `reserve()` for a moment, but
    it can never let more be spent than the real budget -- `spend()` is the
    only thing that touches `_remaining`, and nothing here can raise it.

    **Releasing on error unmasked a pre-existing policy, worth stating
    plainly now that it is visible.** The budget bounds successful reads,
    not requests: `fetch.py` never spends on an `httpx` error or an HTTP
    error status ("errors don't spend" -- nothing was learned that a retry
    couldn't also fail to learn), and that was always the design. Before
    this claim/release mechanism existed, an erroring call still cost
    nothing either. What changed is that a *reservation* for that call used
    to stay stuck (an accident of the leak this section already covers), and
    a stuck reservation happened to throttle a host that errored on every
    request -- accidentally, not by design. Releasing the claim removes that
    accidental brake: a granted host that consistently errors can now be
    requested without limit. This is not a new decision, and closing it
    would be a real one (bounding *attempts*, not just successes, is a
    different grant than the one this class implements) -- it is named here
    so the next reader does not mistake "the throttle went away" for a
    regression rather than the pre-existing policy finally matching what
    the docstring always claimed.

    **Scope is checked before the reservation short-circuit, and this is
    not incidental ordering.** `reserve()`'s idempotency check
    (`call_id in self._reserved: return True`) has to run *after*
    `_in_scope(url)`, never before -- a second whole-branch review caught
    the version that got this backwards. The short-circuit only remembers
    that an id claimed *something*, not what URL it claimed it for; tested
    first, it would re-answer `True` for any URL passed under a
    previously-claimed id, including a host this grant never named or a
    `file://` scheme -- a scope escape, not a budget accounting error, and
    on a research agent whose whole job is reading attacker-controllable
    pages, model-emitted ids make that reachable with two `fetch` calls
    sharing one id in a single assistant message. See `reserve()`'s own
    docstring for the mechanism and `_in_scope()` for the split that fixes
    it without disturbing what `covers()` means to `fetch.py`.
    """

    run_id: UUID
    hosts: frozenset[str]
    budget: int
    _remaining: list[int] = field(default_factory=list, compare=False, repr=False)
    _reserved: set[str] = field(default_factory=set, compare=False, repr=False)

    def __post_init__(self) -> None:
        # dataclass(frozen=True) blocks `self.hosts = ...` and
        # `self._remaining = ...`; object.__setattr__ is the documented
        # escape hatch for exactly this kind of derived init.
        object.__setattr__(self, "hosts", frozenset(host.lower() for host in self.hosts))
        object.__setattr__(self, "_remaining", [self.budget])
        object.__setattr__(self, "_reserved", set())

    @property
    def remaining(self) -> int:
        return self._remaining[0]

    @property
    def spent(self) -> bool:
        return self._remaining[0] <= 0

    def _in_scope(self, url: str) -> bool:
        """Whether `url` is a host and scheme this grant could ever cover --
        deliberately blind to budget, spent or reserved.

        Split out of `covers()` so `reserve()` can test scope *before* its
        idempotency short-circuit without also re-deriving the spent check
        (see `reserve()`'s docstring for why the ordering matters: a
        whole-branch review found that testing the short-circuit first let a
        claimed id re-admit *any* URL, not just the one it was claimed for).

        Total, for the same reason `covers()` is: a URL too malformed for
        `urlsplit` to parse, a non-`http(s)` scheme, or a missing hostname
        are all "not in scope" rather than a raised exception. Without the
        scheme check, `file://a.example/etc/passwd` and the scheme-relative
        `//a.example/p` both yield hostname `a.example` and would read as
        in-scope even though neither is the network request a host grant is
        supposed to authorize.
        """
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        if parts.scheme.lower() not in ("http", "https"):
            return False
        hostname = parts.hostname
        if hostname is None:
            return False
        return hostname.lower() in self.hosts

    def covers(self, url: str) -> bool:
        """Whether `url` may be fetched under this grant right now.

        `not self.spent and self._in_scope(url)` -- unchanged in meaning
        from before `_in_scope` existed. This is the authorization check
        the tool itself consults when it decides whether a completed call
        gets to spend (`fetch.py`'s `covers()`-then-`spend()` pair), and it
        does not know or care about `_reserved`: the gate's authorization
        question ("may a *new* claim be made against what's left") and this
        question ("has this grant actually run out, for this URL") are
        different questions, and folding the second into the first would
        make `fetch.py`'s own spend check swing on reservations it knows
        nothing about and never asked to be blocked by. Does not mutate; a
        spent grant answers `False` for every host, forever, until something
        else calls `spend()`.
        """
        return not self.spent and self._in_scope(url)

    def reserve(self, call_id: str, url: str) -> bool:
        """Claim one unit of budget for `call_id`, or refuse -- the gate's check.

        `_gate_for` (`infrastructure/agent/approval.py`) calls this, not
        `covers()`, so that letting one covered call through *counts against
        the next one evaluated in the same batch*. `covers()` alone cannot do
        that: it only reads `_remaining`, and `_remaining` does not move until
        `fetch.py`'s `spend()` runs, which is after an `await` the gate never
        waits on. Ten covered calls in one assistant message would all read
        `covers() -> True` off the same unspent budget and all leave the
        process before any of their `spend()`s land -- see the class
        docstring and `task-5-review.md` for the reproduction.

        **Scope first, always -- before the idempotency short-circuit, not
        after.** The first version of this method checked `call_id in
        self._reserved` before `covers(url)`, on the reasoning that a call
        already holding a claim should re-answer `True` without re-spending
        budget. A whole-branch review found what that reasoning missed: the
        short-circuit doesn't know the URL it was originally claimed for, so
        it re-answers `True` for *any* URL passed under that id -- one
        assistant message with two `fetch` calls sharing an id (nothing
        dedupes ids within a message; the ids are model-emitted, read off
        the `tool_use` blocks the model itself sampled) claims once for a
        covered host and then admits every later call under that same id
        regardless of host or scheme, unmetered, because `covers()` for the
        out-of-scope URL is `False` and nothing charges it. That is a scope
        escape on a research agent that reads attacker-controllable pages --
        strictly worse than the over-spend it replaced, which stayed inside
        scope. `_in_scope(url)` now runs first, unconditionally, so the
        short-circuit can only ever re-admit a call under the same id *for a
        host and scheme this grant could authorize in the first place*.

        `call_id in self._reserved` next: if this exact call already holds a
        claim for an in-scope URL, re-answer `True` from the existing claim
        rather than trying (and refusing) to take a second one. This is what
        makes `reserve()` safe to call twice for the same call, which
        langgraph actually does -- `interrupt()` raises `GraphInterrupt`, and
        `Command(resume=...)` re-executes `after_model` from the top, so
        every covered call in a message that also contains an interrupting
        one gets evaluated again on the resume pass. A plain count (the
        method's first version, before call ids existed at all) could not
        tell that second evaluation apart from a genuinely new claim,
        double-spent the same call, and at low remaining budget flipped an
        already-admitted call to refused on resume -- one decision back for
        two now-hanging calls, and langchain raised `ValueError`.

        `self.spent` and the remaining-vs-reserved check last, so a claim
        can only be taken while there is real room and the grant has not run
        dry. No `await` anywhere in this method, so two calls evaluated in
        the same synchronous pass (which is how `HumanInTheLoopMiddleware`
        walks one message's tool calls) cannot both observe room for the same
        unit -- the second sees the first's claim and is refused.

        Every successful claim must eventually be released -- by `spend()`
        when it is redeemed, or by `release()` when it is not -- and
        `fetch.py` is written so every return path does one or the other; see
        the class docstring for why that finally had to be added rather than
        accepted as an occasional leak.
        """
        if not self._in_scope(url):
            return False
        if call_id in self._reserved:
            return True
        if self.spent or self._remaining[0] - len(self._reserved) <= 0:
            return False
        self._reserved.add(call_id)
        return True

    def release(self, call_id: str) -> None:
        """Give back a claim that will never be spent.

        A plain `set.discard` -- harmless to call on an id that was never
        reserved (a human-approved, out-of-scope call never held one) and
        harmless to call after `spend()` already removed it (every return
        path in `fetch.py` calls this in a `finally`, whether or not
        `spend()` ran on the way there). Does not touch `_remaining`: giving
        back a claim restores room for a *future* `reserve()`, it does not
        un-spend a unit that was actually charged.
        """
        self._reserved.discard(call_id)

    def spend(self, call_id: str | None = None) -> None:
        """Consume one fetch. The only mutation `covers()` itself reacts to.

        `call_id` releases the reservation it redeems -- `None` is the
        default so every direct-tool test in `test_fetch.py` (which builds a
        grant and calls `spend()` with no gate, and therefore no id, in the
        loop) keeps working unchanged. Discarding an id already absent (an
        id never reserved, or one this same call already released) is a
        no-op, so `fetch.py` calling this and then `release()` in its
        `finally` is not a double-release bug.
        """
        self._remaining[0] -= 1
        if call_id is not None:
            self._reserved.discard(call_id)


class GrantRegistry:
    """Which session holds which grant, for as long as this process runs.

    In-memory and not thread-safe, on the same basis `Recall` gives for its
    own cache: one event loop, no interleaving, so nothing here needs a lock.
    That guarantee covers `register`/`get`/`release` and `FetchGrant.spend`'s
    own decrement (no `await` inside it, so nothing can interleave mid-line
    and no update is lost) -- it does NOT cover a caller's check-then-act
    that spans an `await` between the check and the act, which is exactly
    the pattern `fetch.py` uses (`covers()` before a network read,
    `spend()` after). Two coroutines can both observe `covers() -> True`
    before either has called `spend()`, because "one event loop" only
    means no two lines run at once -- it does not mean two `await`-separated
    steps of the same logical operation run atomically. See
    `infrastructure/agent/fetch.py`'s `build_fetch_tool` docstring for the
    concrete gap this produces and why it is bounded rather than open-ended.

    Memory rather than a projection is load-bearing, not an oversight. A run
    whose stream has no stop event is abandoned (`research_supervisor.py:18-20`
    says such a run is deliberately never reconstructed), and process death
    must revoke every grant so that an abandoned run does not come back
    authorized when the process restarts. Deriving grants from the log at
    fetch time would make authorization outlive the run it was scoped to --
    exactly backwards from what a pre-authorization is supposed to bound.
    """

    def __init__(self) -> None:
        self._grants: dict[UUID, FetchGrant] = {}

    def register(self, session_id: UUID, grant: FetchGrant) -> None:
        self._grants[session_id] = grant

    def get(self, session_id: UUID) -> FetchGrant | None:
        return self._grants.get(session_id)

    def release(self, session_id: UUID) -> None:
        self._grants.pop(session_id, None)

    def is_unattended(self, session_id: UUID) -> bool:
        """True when `session_id` is registered at all, granted or not.

        A later task bounds approvals on sessions nobody is watching; a
        session being *in* the registry -- regardless of what its grant does
        or doesn't cover -- is what "this is an unattended run" means here.
        """
        return session_id in self._grants
