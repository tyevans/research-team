"""Subsystem builders for application wiring: tools, curation ports, stores and runners."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from eventsource import InMemoryEventBus
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.observability import Tracer
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from research_team.infrastructure import config
from research_team.infrastructure.agent.fetch import (
    FETCH_PROMPT,
    build_fetch_tool,
)
from research_team.infrastructure.agent.media_curation_adapter import build_curation_ports
from research_team.infrastructure.agent.recall import PageMemo, Recall
from research_team.infrastructure.agent.search import (
    SEARCH_PROMPT,
    SearchAttempts,
    build_search_tool,
)
from research_team.infrastructure.identity import EventStoreUserRecorder
from research_team.infrastructure.interaction.recorder import EventStoreInteractionRecorder
from research_team.infrastructure.persistence import (
    CorpusRunner,
    EventStoreSessionRepository,
    SessionSummaryRunner,
    TopicRunner,
)
from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore
from research_team.infrastructure.persistence.interaction_log import InteractionLogRunner
from research_team.infrastructure.persistence.read_models import (
    AskConversationRunner,
    AuthoringRunRunner,
    EntityDefinitionRunner,
    MediaProposalRunner,
    OntologyRunner,
    SocraticDialogueRunner,
)
from research_team.infrastructure.persistence.tenants import TenantRunner
from research_team.infrastructure.persistence.users import UserRunner
from research_team.infrastructure.settings import (
    HttpProviderProbe,
    ModelProfileStore,
    SettingsStore,
    build_secret_box,
)
from research_team.infrastructure.telemetry import build_tracer
from research_team.interfaces.web.settings import SettingsDeps
from research_team.research.application.media_curation import (
    MediaCurationTextPort,
    MediaSearchPort,
)
from research_team.session.application.session_service import NO_SEARCH_CLAUSE
from research_team.settings.application.effective import (
    EffectiveSettings,
    SettingsRevision,
)
from research_team.tenancy.application.authorization import (
    Authorizer,
    PermissiveAuthorizer,
    RoleTableAuthorizer,
)
from research_team.wiring.lifecycle import _close_every_step, _run_detached
from research_team.wiring.resources import (
    _LazyArtStore,
    _LazyBlurbCache,
    _LazyCandidateArtStore,
    _LazyOutlineCache,
    _LazyProjectSummaries,
)
from research_team.wiring.runners import (
    _CatalogFeatureRunner,
    _CourseRunner,
)

_DEFAULT = object()


@dataclass(frozen=True)
class BuiltTools:
    """The base set of tools and search state constructed for an application."""

    tools: tuple[BaseTool, ...]
    recall: Recall
    pages: PageMemo
    search_attempts: SearchAttempts | None
    prompt_suffix: str


def build_tools(
    *,
    searxng_url: str | object | None = _DEFAULT,
    limit: int | None = None,
    recall: Recall | None = None,
    pages: PageMemo | None = None,
    build_fetch: Callable[..., BaseTool] = build_fetch_tool,
    build_search: Callable[..., BaseTool] = build_search_tool,
) -> BuiltTools:
    """Construct the unconditional and network tools for the base application.

    Two tools leave the process, and they are withheld differently because
    there are two different things to withhold them with.

    `fetch` is registered unconditionally: there is no instance to leave
    unconfigured, and a research agent that can see five snippets and never
    read a page is not much of one. Its floor of `ask` is the switch instead
    -- present and discoverable, but it cannot reach anything until a person
    says so once. See `TOOL_FLOORS`.

    `web_search` keeps its configuration switch: an instance is a real thing
    someone has to stand up, and "unset means absent" is a stronger promise
    than any gate, so there is no reason to trade it for one.

    One memo for both network tools and for every session this application
    serves. Process-wide rather than per-session because `build_fetch_tool`
    is called once here -- and correct at that scope for the same reason it
    is safe: it holds only responses from public URLs, which are the same
    bytes whoever asked. Nothing project-scoped may ever go in it.
    """
    resolved_recall = recall if recall is not None else Recall()
    # One store, shared by both `fetch` builds exactly as `recall` is: it holds
    # only bytes from public URLs, which are the same whoever asked. Nothing
    # project-scoped may ever go in it.
    resolved_pages = pages if pages is not None else PageMemo()
    tools: tuple[BaseTool, ...] = (build_fetch(recall=resolved_recall, pages=resolved_pages),)
    prompt_suffix = FETCH_PROMPT

    search_attempts: SearchAttempts | None = None
    searxng = config.searxng_url() if searxng_url is _DEFAULT else searxng_url  # type: ignore[assignment]
    if searxng is not None:
        # One instance, handed to both the tool and the middleware --
        # not two `SearchAttempts()` calls. Two instances would mean the
        # middleware resets a counter the tool never reads and the tool's own
        # counter never resets, so an empty streak would silently outlive the
        # turn that produced it and eventually wedge `web_search` for good.
        search_attempts = SearchAttempts()
        search_limit = limit if limit is not None else config.searxng_results()
        tools += (
            build_search(
                searxng,
                limit=search_limit,
                recall=resolved_recall,
                attempts=search_attempts,
            ),
        )
        prompt_suffix += SEARCH_PROMPT
    else:
        prompt_suffix += NO_SEARCH_CLAUSE

    return BuiltTools(
        tools=tools,
        recall=resolved_recall,
        pages=resolved_pages,
        search_attempts=search_attempts,
        prompt_suffix=prompt_suffix,
    )


def build_curation_tools(
    extraction_model: BaseChatModel,
    *,
    searxng_url: str | object | None = _DEFAULT,
    model_name: str | None = None,
    limit: int | None = None,
) -> tuple[MediaCurationTextPort | None, MediaSearchPort | None]:
    """Construct media curation text and search ports.

    `None`/`None` when `searxng` is unconfigured: matching `search_attempts`
    above: the curation chain's search port needs the same instance the
    agent's own `web_search` tool does, and a build with neither configured
    has nothing for `MediaCurationService` to search with either. The text port
    is gated the same way rather than built unconditionally, so the pair
    answers `create_app`'s 503 check together instead of one half being
    present for a service the other half can never actually run.
    """
    searxng = config.searxng_url() if searxng_url is _DEFAULT else searxng_url  # type: ignore[assignment]
    if searxng is None:
        return None, None

    resolved_model_name = model_name if model_name is not None else config.curation_model()
    resolved_limit = limit if limit is not None else config.searxng_results()
    return build_curation_ports(
        extraction_model,
        model_name=resolved_model_name,
        searxng_url=searxng,
        limit=resolved_limit,
    )


@dataclass(frozen=True)
class BuiltStores:
    """The complete bundle of stores, runners, and repositories wired for the application."""

    repository: EventStoreSessionRepository
    corpus: CorpusRunner
    blob_store: FilesystemBlobStore
    topics: TopicRunner
    settings_revision: SettingsRevision
    settings_store: SettingsStore
    profile_store: ModelProfileStore
    settings_secrets: Any
    settings_deps: SettingsDeps
    effective_settings: EffectiveSettings
    definition_invalidation: EntityDefinitionRunner
    ontology: OntologyRunner
    media_proposals: MediaProposalRunner
    asks: AskConversationRunner
    dialogues: SocraticDialogueRunner
    users: UserRunner
    user_recorder: EventStoreUserRecorder
    authoring: AuthoringRunRunner
    interaction_store: SQLiteEventStore
    interaction_bus: InMemoryEventBus
    interaction_log: InteractionLogRunner
    interaction_recorder: EventStoreInteractionRecorder
    tenants: TenantRunner
    authorizer: Authorizer
    summaries: SessionSummaryRunner
    catalog_runner: _CatalogFeatureRunner
    blurb_cache: _LazyBlurbCache
    art_store: _LazyArtStore
    project_summaries: _LazyProjectSummaries
    candidate_art_store: _LazyCandidateArtStore
    outline_cache: _LazyOutlineCache
    course_runner: _CourseRunner


def build_stores(
    *,
    resolved_path: str | None = None,
    resolved_interaction_path: str | None = None,
    resolved_tracer: Tracer | None = None,
    blob_root: str | None = None,
) -> BuiltStores:
    """Construct all event stores, projections, runners, and repositories.

    Any partial failure during construction unwinds whatever was already
    opened before propagating the exception, preventing worker thread leaks.
    """
    path = resolved_path if resolved_path is not None else config.default_db_path()
    interaction_path = (
        resolved_interaction_path
        if resolved_interaction_path is not None
        else config.interaction_db_path()
    )
    tracer = resolved_tracer if resolved_tracer is not None else build_tracer()
    blobs_dir = blob_root if blob_root is not None else config.blob_root()

    opened: list[tuple[str, Callable[[], Awaitable[object]]]] = []

    try:
        # Opened before the tools so the knowledge adapter can share this
        # connection's event store and snapshot store rather than opening its own
        # (BACKLOG B5: a second `SQLiteSnapshotStore` leaks a non-daemon thread).
        repository = EventStoreSessionRepository.open(path)
        opened.append(("repository", repository.close))

        corpus = CorpusRunner(repository.store, path, repository.publisher, tracer)
        opened.append(("corpus", corpus.stop))

        blob_store = FilesystemBlobStore(blobs_dir)

        topics = TopicRunner(repository.store, path, repository.publisher, tracer)
        opened.append(("topics", topics.stop))

        settings_revision = SettingsRevision()
        settings_store = SettingsStore(path, tracer, settings_revision)
        profile_store = ModelProfileStore(path, tracer, settings_revision)
        settings_secrets = build_secret_box()
        settings_deps = SettingsDeps(
            store=settings_store,
            secrets=settings_secrets,
            probe=HttpProviderProbe(),
            profiles=profile_store,
        )
        opened.append(("settings_deps", settings_deps.close))

        effective_settings = EffectiveSettings(
            store=settings_store,
            secrets=settings_secrets,
            profiles=profile_store,
            revision=settings_revision,
        )

        definition_invalidation = EntityDefinitionRunner(
            repository.store, path, repository.publisher, tracer
        )
        opened.append(("definition_invalidation", definition_invalidation.stop))

        ontology = OntologyRunner(repository.store, path, repository.publisher, tracer)
        opened.append(("ontology", ontology.stop))

        media_proposals = MediaProposalRunner(
            repository.store, path, repository.publisher, tracer
        )
        opened.append(("media_proposals", media_proposals.stop))

        asks = AskConversationRunner(repository.store, path, repository.publisher, tracer)
        opened.append(("asks", asks.stop))

        dialogues = SocraticDialogueRunner(
            repository.store, path, repository.publisher, tracer
        )
        opened.append(("dialogues", dialogues.stop))

        users = UserRunner(repository.store, path, repository.publisher, tracer)
        opened.append(("users", users.stop))

        user_recorder = EventStoreUserRecorder(repository.store, repository.publisher, users)

        authoring = AuthoringRunRunner(repository.store, path, repository.publisher, tracer)
        opened.append(("authoring", authoring.stop))

        interaction_store = SQLiteEventStore(interaction_path)
        opened.append(("interaction_store", interaction_store.close))

        interaction_bus = InMemoryEventBus()
        interaction_log = InteractionLogRunner(
            interaction_store,
            interaction_path,
            interaction_bus,
            tracer,
        )
        opened.append(("interaction_log", interaction_log.stop))

        interaction_recorder = EventStoreInteractionRecorder(
            interaction_store, interaction_bus
        )

        tenants = TenantRunner(repository.store, path, repository.publisher, tracer)
        opened.append(("tenants", tenants.stop))

        authorizer: Authorizer = (
            RoleTableAuthorizer(tenants, config.admin_subjects())
            if config.authorization_enabled()
            else PermissiveAuthorizer()
        )

        summaries = SessionSummaryRunner(repository.store, path, repository.publisher, tracer)
        opened.append(("summaries", summaries.stop))

        catalog_runner = _CatalogFeatureRunner(repository.store, repository.publisher, path)
        opened.append(("catalog_runner", catalog_runner.stop))

        blurb_cache = _LazyBlurbCache(path)
        opened.append(("blurb_cache", blurb_cache.close))

        art_store = _LazyArtStore(path)
        opened.append(("art_store", art_store.close))

        project_summaries = _LazyProjectSummaries(path)
        opened.append(("project_summaries", project_summaries.close))

        candidate_art_store = _LazyCandidateArtStore(path)
        opened.append(("candidate_art_store", candidate_art_store.close))

        outline_cache = _LazyOutlineCache(path)
        opened.append(("outline_cache", outline_cache.close))

        course_runner = _CourseRunner(repository.store, repository.publisher, path)
        opened.append(("course_runner", course_runner.stop))

        return BuiltStores(
            repository=repository,
            corpus=corpus,
            blob_store=blob_store,
            topics=topics,
            settings_revision=settings_revision,
            settings_store=settings_store,
            profile_store=profile_store,
            settings_secrets=settings_secrets,
            settings_deps=settings_deps,
            effective_settings=effective_settings,
            definition_invalidation=definition_invalidation,
            ontology=ontology,
            media_proposals=media_proposals,
            asks=asks,
            dialogues=dialogues,
            users=users,
            user_recorder=user_recorder,
            authoring=authoring,
            interaction_store=interaction_store,
            interaction_bus=interaction_bus,
            interaction_log=interaction_log,
            interaction_recorder=interaction_recorder,
            tenants=tenants,
            authorizer=authorizer,
            summaries=summaries,
            catalog_runner=catalog_runner,
            blurb_cache=blurb_cache,
            art_store=art_store,
            project_summaries=project_summaries,
            candidate_art_store=candidate_art_store,
            outline_cache=outline_cache,
            course_runner=course_runner,
        )
    except BaseException:
        if opened:
            _run_detached(_close_every_step(*reversed(opened)))
        raise
