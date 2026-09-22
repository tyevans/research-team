"""Model endpoints and embedding providers."""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from redstring import EmbeddingProvider
from redstring.llm.adapters.langchain import NO_THINKING
from redstring.llm.adapters.langchain_embedding import LangChainEmbeddingProvider

from research_team.infrastructure import config
from research_team.settings.application.effective import (
    ExtractionSettings,
    ResearchSettings,
)

__all__ = [
    "build_embedding_provider",
    "build_extraction_model",
    "build_model",
]


def build_model(settings: ResearchSettings | None = None) -> BaseChatModel:
    """The OpenAI-compatible endpoint the agent talks to.

    `settings` is one project's resolved answer, from
    `application/effective.ResearchSettings`. `None` is the process answer --
    the environment, then the built-in default, through `config` exactly as
    this function always did -- which is what a CLI run, the REPL and every
    test that never names a project still get.

    The parameter is the whole of what makes the settings page's `Models`
    group reach a turn. Without it this function answers for the *process*,
    is called once in `_build_application`, and bakes its answer into an
    executor that outlives every project: a model saved against a project
    resolved correctly through the API and was read by nothing. See
    `EffectiveSettings.research`.
    """
    if settings is not None:
        return ChatOpenAI(
            model=settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key,
            temperature=0,
        )
    return ChatOpenAI(
        model=config.model_name(),
        base_url=config.base_url(),
        api_key=config.api_key(),
        temperature=0,
    )


def build_extraction_model(settings: ExtractionSettings | None = None) -> BaseChatModel:
    """The same endpoint as `build_model`, told not to think before answering.

    A second `ChatOpenAI` rather than `build_model().bind(extra_body=...)`,
    for two reasons. `extra_body` is a constructor field, and `bind` returns a
    `RunnableBinding`, not the `BaseChatModel` that `LangChainLlmProvider`
    is typed against. And the agent and the extractor genuinely want different
    request bodies, so two objects says what is true: this one is not the
    agent's model with a decoration, it is the extractor's model.

    redstring 0.4.0 made thinking-off the default for extraction, but only
    inside `LangChainLlmProvider.openai_compatible`. This project builds its
    own chat model and uses `__init__`, so that default never reached it --
    which is the bug this exists to close. `NO_THINKING` is imported rather
    than spelled out so a rename or a change of shape upstream breaks the
    build instead of quietly leaving extraction thinking again.

    See `config.extraction_thinking` for the measurement, the env override and
    the backends this field is rejected by.

    `settings` is one project's resolved answer, from
    `application/effective.EffectiveSettings`. `None` is the process answer --
    the environment, then the built-in default -- read through `config` exactly
    as this function always did, which is what a CLI run and every test that
    never names a project still get. The two branches read the same eight
    values in the same order; they differ only in how many layers were
    consulted to produce them.
    """
    if settings is not None:
        return ChatOpenAI(
            model=settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key,
            temperature=0,
            extra_body=None if settings.thinking else dict(NO_THINKING),
        )
    return ChatOpenAI(
        # `extraction_model()`, not `model_name()`. The two are the same string
        # on a default install and stop being so the moment anyone sets
        # `AGENT_EXTRACTION_MODEL` -- which is the point: this client already
        # differed from the agent's in everything but the name it sent.
        model=config.extraction_model(),
        base_url=config.base_url(),
        api_key=config.api_key(),
        temperature=0,
        extra_body=None if config.extraction_thinking() else dict(NO_THINKING),
    )


def build_embedding_provider() -> EmbeddingProvider:
    """The embedding endpoint, wrapped in redstring's port.

    A third client rather than a third use of `build_model`, for the reason
    `build_extraction_model` is a second one: this is a different model at a
    possibly different address answering a different API, and the only thing
    it shares with the chat client is that both speak OpenAI's protocol.

    `dimensions` is passed to `OpenAIEmbeddings` **and** declared to
    `LangChainEmbeddingProvider`, which looks redundant and is not. The first
    asks the server for that width -- OpenAI's `text-embedding-3-*` honour it
    and truncate, most local servers ignore it and return their native width.
    The second is what redstring checks the `VectorStore` against before
    embedding anything. Declaring only the second would let a server quietly
    return 1024 components into a store built for 768, which fails at the
    first write with `DimensionMismatchError` -- a poison event, so the ingest
    that triggered it is unrecoverable rather than retryable.

    Nothing here contacts the server. A wrong model name, a wrong width or an
    endpoint that serves no embeddings all surface on the first `embed`, which
    is during an ingest. `config.embedding_model` refuses an unset name here
    instead, which is the one failure that can be moved earlier.
    """
    return LangChainEmbeddingProvider(
        OpenAIEmbeddings(
            model=config.embedding_model(),
            base_url=config.embedding_base_url(),
            api_key=config.embedding_api_key(),
            dimensions=config.embedding_dimension(),
            check_embedding_ctx_length=False,
        ),
        model=config.embedding_model(),
        dimension=config.embedding_dimension(),
    )
