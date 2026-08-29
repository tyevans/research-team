"""The resolved settings a piece of work actually runs on.

`application/settings.py` resolves a key for a scope chain. This is the other
half: the small number of *bundles* the system reads together, resolved once
for a project and handed to the code that builds a client. Without it the
whole scoped store is decorative -- a project-scoped extraction model resolves
correctly through the API and the extraction run still uses the process-wide
value, because `infrastructure/config.py` answers for the process and a
`config.extraction_model()` call has no idea which project it is serving.

**Why a snapshot per project, and not the two alternatives.**

Threading a resolved-settings object down through the application layer was
rejected for reach: `build_model` is called from inside an executor built once
per process, and the argument would have to cross every layer between. A
context variable was rejected for the deciding case. Extraction, course
authoring, catalog sweeps and the media reconcile loop all run *detached* from
any request -- `asyncio.create_task` copies the context at creation, which is
already unreliable for a task scheduled from a route (CLAUDE.md, "Web
middleware", on what `BaseHTTPMiddleware` does to the routes that hand work to
a background task), and is simply empty for the sweep loops, which no request
ever entered. Those detached runs are exactly the ones whose model choice
matters most, so an approach that only works inside a request is the wrong
approach here.

What every one of them *does* have is a project id: `open_graph`, the sweeps
and the authoring runner are all already parametrised by one. So the project id
is the key, resolution is a plain `await` on the id the caller already holds,
and there is no ambient state to be missing.

**The headless path is not a second code path.** `SettingsResolver` with no
store and an empty chain resolves the environment, then the built-in default --
which is exactly and only what `config.py` does. So a CLI run, and every test
in the suite, take the same call and get the same answer they got before this
module existed; there is no `if project_id is None` branch choosing between two
resolvers, which is what would have let the two drift.

**Staleness is designed against at the store, not at the route.** A cache keyed
on the project id alone goes stale the moment somebody saves a setting, and
"the route remembers to invalidate" is documentation rather than a contract
(CLAUDE.md, "Checkpoints over model output"). `SettingsRevision` is bumped by
the store adapters themselves -- the single production writers for both tables
-- so a route added tomorrow that writes through them invalidates this cache
without knowing the cache exists.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from research_team.application.settings import (
    ModelProfileService,
    ModelProfileStorePort,
    SecretBoxPort,
    SettingsResolver,
    SettingsStorePort,
)
from research_team.domain.settings import ModelProfile, ModelRole, Scope, ScopeRef


class SettingsRevision:
    """A counter that rises on every settings write.

    Not a timestamp: two writes inside one clock tick are indistinguishable by
    time, and the failing case -- save a setting, immediately start a run -- is
    precisely a pair of events milliseconds apart. An integer that only ever
    goes up cannot have that problem.

    Deliberately not locked. Everything here runs on one event loop, and a lock
    would be guarding an increment that is already atomic for the only reader
    that exists.
    """

    def __init__(self) -> None:
        self._value = 0

    @property
    def value(self) -> int:
        return self._value

    def bump(self) -> None:
        self._value += 1


@dataclass(frozen=True)
class ExtractionSettings:
    """Everything one project's knowledge extraction is configured by.

    A bundle rather than eight separate awaits at the call site, because the
    call site is `open_graph`, and eight round trips to SQLite to build one
    adapter is eight chances for two of them to disagree about a value somebody
    changed in between.

    `model` is both the name sent to the endpoint and the label redstring
    stamps on the extraction. One field, because the two being read separately
    is how they came to be able to disagree -- see the comment at the
    `LangChainLlmProvider` call in `composition.py`.
    """

    model: str
    base_url: str
    api_key: str
    thinking: bool
    concurrency: int
    chunk_size: int
    consolidation_batch: int
    knowledge_domain: str


@dataclass(frozen=True)
class ResearchSettings:
    """What one project's *agent* talks to.

    Three fields against `ExtractionSettings`' eight, and the difference is not
    an oversight: extraction is a pipeline with its own concurrency, chunking
    and domain, where a turn is one conversation with an endpoint. Everything
    else a turn is shaped by -- its tools, its subagents, its context strategy
    -- is chosen per turn already and by something other than a setting.

    A bundle rather than three awaits at the call site, for
    `ExtractionSettings`' reason: the three move together. A model name taken
    from one resolve and an endpoint from another can straddle a write and send
    a local model's name to a hosted endpoint.
    """

    model: str
    base_url: str
    api_key: str


class EffectiveSettings:
    """Resolved bundles, per project, cached until something is written.

    Constructed once in composition and handed to the places that build
    clients. Holds the stores rather than a resolver, because a resolver
    captures `os.environ` at construction and this object outlives any
    particular read.

    Every argument defaults to `None`, which is the headless build: no store,
    no secrets, no profiles, and every answer therefore the environment's or
    the built-in default's. That is the same object a CLI run gets, so the
    no-scope path is exercised by construction rather than by a branch.
    """

    def __init__(
        self,
        store: SettingsStorePort | None = None,
        secrets: SecretBoxPort | None = None,
        profiles: ModelProfileStorePort | None = None,
        revision: SettingsRevision | None = None,
    ) -> None:
        self._store = store
        self._secrets = secrets
        self._profiles = profiles
        self._revision = revision if revision is not None else SettingsRevision()
        self._extraction: dict[UUID | None, tuple[int, ExtractionSettings]] = {}
        self._research: dict[UUID | None, tuple[int, ResearchSettings]] = {}

    def _chain(self, project_id: UUID | None) -> list[ScopeRef]:
        """The scope chain for a project.

        Project only. User and tenant are real layers that `SettingsResolver`
        already walks, and nothing here can name one: W-A owns identity and
        W-B owns tenancy, and a chain that guessed at a user id would resolve
        confidently against the wrong person. An empty chain is the headless
        answer and is not a special case -- it is the same walk with nothing
        above the environment.
        """
        if project_id is None:
            return []
        return [ScopeRef(Scope.PROJECT, str(project_id))]

    def _resolver(self) -> SettingsResolver:
        return SettingsResolver(self._store, self._secrets)

    async def extraction(self, project_id: UUID | None) -> ExtractionSettings:
        """This project's extraction configuration.

        Cached on `(project_id, revision)`. A write bumps the revision, so the
        *next* call after a change resolves afresh -- which is the behaviour
        `test_a_changed_extraction_model_reaches_the_next_run` asserts, by
        reading the model a run would use rather than by inspecting the cache.
        """
        cached = self._extraction.get(project_id)
        if cached is not None and cached[0] == self._revision.value:
            return cached[1]
        resolved = await self._resolve_extraction(project_id)
        self._extraction[project_id] = (self._revision.value, resolved)
        return resolved

    async def research(self, project_id: UUID | None) -> ResearchSettings:
        """This project's agent configuration.

        Cached on `(project_id, revision)`, exactly as `extraction` is, and for
        the same reason: a turn resolves this on the way in, and a per-turn
        round trip to SQLite for three values that change once a month is a
        cost paid on every message.

        The bundle this method returns is the whole of what made the settings
        page's `Models` group real for the agent. Before it, `AGENT_MODEL`,
        `AGENT_BASE_URL` and `AGENT_API_KEY` were stored, resolved correctly
        through `/api/settings/resolved`, and read by nothing on the turn path
        -- `build_model()` answers for the process and is called once, so a
        person could set a model, watch it save, watch it resolve, and watch
        every turn go to the endpoint it always had. Which is exactly what this
        module's own docstring says the store is without a bundle to feed.
        """
        cached = self._research.get(project_id)
        if cached is not None and cached[0] == self._revision.value:
            return cached[1]
        resolved = await self._resolve_research(project_id)
        self._research[project_id] = (self._revision.value, resolved)
        return resolved

    async def _resolve_research(self, project_id: UUID | None) -> ResearchSettings:
        chain = self._chain(project_id)
        resolver = self._resolver()
        keys = ("model", "base_url")
        answers = {
            answer.key: answer.value for answer in await resolver.resolve_all(keys, chain)
        }
        model = str(answers["model"])
        base_url = str(answers["base_url"])
        api_key = await resolver.secret("api_key", chain)

        # A selected profile wins, and carries all three together -- see
        # `_resolve_extraction`'s note for what taking them from two places
        # would send where.
        profile = await self._profile_for(ModelRole.RESEARCH, chain, resolver)
        if profile is not None:
            model = profile.model
            if profile.base_url:
                base_url = profile.base_url
            if profile.credential_key is not None:
                credential = await resolver.secret(profile.credential_key, chain)
                if credential is not None:
                    api_key = credential

        return ResearchSettings(
            model=model,
            base_url=base_url,
            api_key=str(api_key) if api_key is not None else "",
        )

    async def _resolve_extraction(self, project_id: UUID | None) -> ExtractionSettings:
        chain = self._chain(project_id)
        resolver = self._resolver()
        keys = (
            "extraction_model",
            "model",
            "base_url",
            "extraction_thinking",
            "extraction_concurrency",
            "extraction_chunk_size",
            "consolidation_batch",
            "knowledge_domain",
        )
        answers = {
            answer.key: answer.value for answer in await resolver.resolve_all(keys, chain)
        }
        # `extraction_model` has no default of its own and falls back to the
        # chat model, which is what `config.extraction_model` does. Kept the
        # same way round here rather than given a default in the registry:
        # "unset means the chat model" is the documented behaviour, and a
        # default would make the fallback invisible on the settings form.
        model = answers["extraction_model"] or answers["model"]
        base_url = str(answers["base_url"])
        api_key = await resolver.secret("api_key", chain)

        # A selected profile wins over the settings above -- that is what
        # selecting one means. It carries its own endpoint and credential, so
        # all three move together; taking the model name from a profile and
        # the key from the setting beside it would send an Anthropic model name
        # to a local vLLM with a key neither accepts.
        profile = await self._profile_for(ModelRole.EXTRACTION, chain, resolver)
        if profile is not None:
            model = profile.model
            if profile.base_url:
                base_url = profile.base_url
            if profile.credential_key is not None:
                credential = await resolver.secret(profile.credential_key, chain)
                if credential is not None:
                    api_key = credential

        return ExtractionSettings(
            model=str(model),
            base_url=base_url,
            api_key=str(api_key) if api_key is not None else "",
            thinking=bool(answers["extraction_thinking"]),
            concurrency=int(answers["extraction_concurrency"]),  # type: ignore[arg-type]
            chunk_size=int(answers["extraction_chunk_size"]),  # type: ignore[arg-type]
            consolidation_batch=int(answers["consolidation_batch"]),  # type: ignore[arg-type]
            knowledge_domain=str(answers["knowledge_domain"]),
        )

    async def _profile_for(
        self, role: ModelRole, chain: Iterable[ScopeRef], resolver: SettingsResolver
    ) -> ModelProfile | None:
        """The profile selected for `role`, or None.

        Parametrised by role rather than one method per role: the two callers
        want the identical walk over the identical selection list, and a second
        copy differing only in an enum member is the shape that drifts.

        `None` covers three cases a caller does not need to tell apart: no
        profile store wired, no selection made, and a selection pointing at a
        profile no scope in the chain defines. The third is reported as
        `dangling` on the settings form, which is where a person can act on it;
        refusing to run here would take extraction down for a stale selection
        rather than falling back to the setting underneath.
        """
        if self._profiles is None:
            return None
        roles = await ModelProfileService(self._profiles, resolver).roles(chain)
        for selected in roles:
            if selected.role is role:
                return selected.profile
        return None
