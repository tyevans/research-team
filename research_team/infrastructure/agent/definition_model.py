"""`DefinitionTextPort` over a LangChain chat model.

Four lines of adapter, and the whole reason it exists is that those four
lines are the only place LangChain's vocabulary is allowed to meet the
definition use case: `research_team/application/entity_definitions.py` states
its need as one method and one property so that `tests/test_architecture.py`
can keep `BaseChatModel` out of the layer above.

Beside `deep_agent.py` rather than in `infrastructure/knowledge/` with the
graph and usage adapters, because what it adapts is a chat model, and every
other `BaseChatModel` in this codebase is built or wrapped in this package.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage


class ChatModelDefinitionText:
    """`DefinitionTextPort` over whichever chat model composition hands it.

    **The extraction model, in practice, and not a second client.** A
    definition is the same job extraction already does -- read this material,
    answer with JSON about it, invent nothing -- against the same endpoint,
    and `build_extraction_model` has already had the one decision that
    matters for it taken (thinking off; see that function). A dedicated model
    was considered during design and declined: it would double the
    configuration surface, and the first time the two drifted apart the
    symptom would be definitions that reason aloud into a JSON parser that
    then answers `None` for every entity.

    The cost of sharing is stated rather than hidden: whatever
    `AGENT_EXTRACTION_THINKING` and `AGENT_MODEL` say applies to both, so a
    build tuned for extraction is tuning definitions too. That is acceptable
    while they want the same thing; when they stop wanting the same thing,
    this constructor is where the second model arrives.

    `model_name` is passed in rather than read off the client, because it is
    stored on every cached row (`EntityDefinitionRow.model`) as the answer to
    "what wrote this text", and `BaseChatModel` offers no portable attribute
    that reliably holds it -- `ChatOpenAI.model_name` exists, a fake in a test
    has nothing.
    """

    def __init__(self, model: BaseChatModel, *, model_name: str) -> None:
        self._model = model
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, prompt: str) -> str:
        # One `HumanMessage` and no `SystemMessage`: the grounding rules are
        # in the prompt `build_prompt` assembles, deliberately next to the
        # material they are a rule about, and splitting them across two
        # messages here would put half of that contract somewhere the
        # application-layer test of the prompt could not see it.
        response = await self._model.ainvoke([HumanMessage(prompt)])
        return str(response.content)
