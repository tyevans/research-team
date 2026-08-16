"""The media-curation ports (`MediaCurationTextPort`, `MediaSearchPort`),
built over a chat model and a SearXNG instance.

`ChatModelCurationText` is structurally identical to `ChatModelOntologyText`
and `ChatModelDefinitionText` for the reason those two give each other: this
is the one place LangChain's vocabulary is allowed to meet
`application/media_curation.py`'s ports, which is what keeps `BaseChatModel`
and `with_structured_output` (used nowhere in this repository) out of the
layer above -- `tests/test_architecture.py` enforces the direction.

`SearxngMediaSearch` is a second, narrower client against the same instance
`infrastructure/agent/search.py`'s `web_search` tool talks to, not a shared
one. It deliberately does not take a `Recall` or a `SearchAttempts`: both
bound a *model's* own searching within one turn -- how many times it may ask,
how long it may keep asking after empties -- and this port is called from a
fixed three-stage chain whose call count is already bounded by
`MAX_NEEDS_PER_TOPIC` * `MAX_QUERIES_PER_NEED` in `media_curation.py`. Adding
either here would be bounding a bound, and adding `Recall` specifically would
be adding a cache nothing asked for -- the tempting fix for someone who later
notices the chain can re-search a need it has already searched, which is not
a bug: a need's queries are generated once per `curate()` call and the pool
they build is used once, by stage 3, in the same call.
"""

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from research_team.application.media_curation import (
    MediaCurationTextPort,
    MediaSearchPort,
    SearchResult,
)
from research_team.infrastructure.agent.search import TIMEOUT, parse_results


class ChatModelCurationText:
    """`MediaCurationTextPort` over whichever chat model composition hands it.

    `model_name` is passed in rather than read off the client, mirroring
    `ChatModelOntologyText` -- `BaseChatModel` offers no portable attribute
    that reliably holds it, and every stage's `IdentifyMediaNeeds` /
    `ProposeMedia` event records this string as the answer to "what decided
    this".
    """

    def __init__(self, model: BaseChatModel, *, model_name: str) -> None:
        self._model = model
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, prompt: str) -> str:
        # One `HumanMessage`, no `SystemMessage` -- mirrors
        # `ChatModelOntologyText.generate` and `ChatModelDefinitionText.generate`
        # for the same reason: the rules the reply must follow live in the
        # prompt each `_*_prompt` function in `media_curation.py` builds,
        # beside the material they constrain, not split into a second message.
        response = await self._model.ainvoke([HumanMessage(prompt)])
        return str(response.content)


class SearxngMediaSearch:
    """`MediaSearchPort` over one SearXNG instance, via `parse_results`.

    Calls `parse_results`, never `format_results`: the chain wants
    `SearchResult`s to pool, filter against the ignore list and judge by
    index, not a prose block rendered for a model to read. `format_results`
    exists for `web_search`'s reply to the agent; this port has no reply to
    a model to render.

    `categories` is passed straight through to the instance, exactly as
    `build_search_tool` passes it -- see that function's docstring. This
    port does not further validate or default it: stage 2 in
    `media_curation.py` chooses the category, and an unknown one is answered
    by the instance the way any of its own users' would be.

    A malformed payload (`parse_results` returning `None`) becomes `()`, not
    `None` or a raise -- `MediaSearchPort.search` promises a tuple, and this
    is the one place the port's contract has to decide what "the instance
    sent something that wasn't a results object" means for a caller with no
    sentinel to check. Silently empty is consistent with every parser in
    `media_curation.py`: a search that finds nothing usable is retried by the
    chain running again for this need's next query, not by this port raising.
    """

    def __init__(
        self,
        base_url: str,
        *,
        limit: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._limit = limit
        self._client = client

    async def search(self, query: str, categories: str) -> tuple[SearchResult, ...]:
        owned = self._client is None
        http = self._client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            response = await http.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "categories": categories},
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owned:
                await http.aclose()
        return parse_results(payload, self._limit) or ()


def build_curation_ports(
    model: BaseChatModel,
    *,
    model_name: str,
    searxng_url: str,
    limit: int,
    client: httpx.AsyncClient | None = None,
) -> tuple[MediaCurationTextPort, MediaSearchPort]:
    """The two ports the curation chain runs over, built together.

    Takes an already-built `model` rather than building one itself, mirroring
    how `ChatModelOntologyText` and `ChatModelDefinitionText` are wired in
    `composition.py`: which client and which `model_name` this points at is
    `config.curation_model()`'s question to answer, not this function's --
    keeping the read out of here is what lets every test in
    `test_media_curation_adapter.py` build a port without touching the
    environment.
    """
    return (
        ChatModelCurationText(model, model_name=model_name),
        SearxngMediaSearch(searxng_url, limit=limit, client=client),
    )
