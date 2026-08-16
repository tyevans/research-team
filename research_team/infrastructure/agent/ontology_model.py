"""`OntologyTextPort` over a LangChain chat model.

Beside `definition_model.py` and structurally identical to it, for the reason
that file gives: these few lines are the only place LangChain's vocabulary is
allowed to meet the discovery use case.
`research_team/application/ontology_discovery.py` states its need as one method
and one property so that `tests/test_architecture.py` can keep `BaseChatModel`
out of the layer above.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage


class ChatModelOntologyText:
    """`OntologyTextPort` over whichever chat model composition hands it.

    **The extraction model, in practice, and not a second client.** Discovery is
    the same job extraction already does -- read this material, answer with JSON
    about it, invent nothing -- against the same endpoint, and
    `build_extraction_model` has already taken the one decision that matters for
    it (thinking off). A dedicated model was declined for the reason
    `ChatModelDefinitionText` gives: it doubles the configuration surface, and
    the first time the two drifted apart the symptom would be a model reasoning
    aloud into a JSON parser that then refuses every document.

    The cost of sharing is stated rather than hidden: whatever
    `AGENT_EXTRACTION_THINKING` and `AGENT_MODEL` say applies to both, so a
    build tuned for extraction is tuning discovery too. That is acceptable while
    they want the same thing; when they stop wanting the same thing, this
    constructor is where the second model arrives.

    `model_name` is passed in rather than read off the client, because it is
    stored on every class row as the answer to "what found this", and
    `BaseChatModel` offers no portable attribute that reliably holds it.
    """

    def __init__(self, model: BaseChatModel, *, model_name: str) -> None:
        self._model = model
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, prompt: str) -> str:
        # One `HumanMessage` and no `SystemMessage`: the rules constraining what
        # may be claimed about the document are in the prompt `build_prompt`
        # assembles, deliberately next to the material they are a rule about.
        # Splitting them across two messages would put half of that contract
        # somewhere the application-layer test of the prompt could not see it.
        response = await self._model.ainvoke([HumanMessage(prompt)])
        return str(response.content)
