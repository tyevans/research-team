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
    """

    run_id: UUID
    hosts: frozenset[str]
    budget: int
    _remaining: list[int] = field(default_factory=list, compare=False, repr=False)

    def __post_init__(self) -> None:
        # dataclass(frozen=True) blocks `self.hosts = ...` and
        # `self._remaining = ...`; object.__setattr__ is the documented
        # escape hatch for exactly this kind of derived init.
        object.__setattr__(self, "hosts", frozenset(host.lower() for host in self.hosts))
        object.__setattr__(self, "_remaining", [self.budget])

    @property
    def remaining(self) -> int:
        return self._remaining[0]

    @property
    def spent(self) -> bool:
        return self._remaining[0] <= 0

    def covers(self, url: str) -> bool:
        """Whether `url` may be fetched under this grant right now.

        Total: a URL too malformed for `urlsplit` to make sense of --
        `urlsplit("https://[::1/x")` raises `ValueError: Invalid IPv6 URL`,
        the same case `normalize_url` guards -- is "not covered" rather than a
        raised exception reaching the tool call. Does not mutate; a spent
        grant answers `False` for every host, forever, until something else
        calls `spend()`.

        Scheme-checked, not just host-checked: this is the authorization check
        both `fetch`'s gate and the tool itself consult, and it is written to
        answer correctly on its own rather than lean on `fetch.py`'s own
        scheme guard, which lives in a different file and can change under a
        different task. Without this, `file://a.example/etc/passwd` and the
        scheme-relative `//a.example/p` both yield hostname `a.example` and
        would read as covered even though neither is the network request a
        host grant is supposed to authorize.
        """
        if self.spent:
            return False
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

    def spend(self) -> None:
        """Consume one fetch. The only mutation this frozen value permits."""
        self._remaining[0] -= 1


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
