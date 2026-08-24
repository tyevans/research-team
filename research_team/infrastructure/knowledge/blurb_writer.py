"""`BlurbTextPort` over a LangChain chat model, and the one check it can run.

The check itself lives in `grounding.py` -- it is shared with the outline
writer, and its reasoning (why it is weaker than `entity_definitions`, which
false-accept it tolerates, why `SENTENCE_OPENERS` is a closed list) moved
there with it rather than being restated here in a second voice that can
drift from the first.

What stays here is the part specific to a blurb: the prompt, and the two
refusals a blurb makes. An empty reply is refused rather than stored, and a
reply with any ungrounded capitalised run is refused whole -- `grounding`'s
docstring says why that is the conservative direction to fail in.
"""

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.grounding import anchor_lines, ungrounded_runs

_PROMPT = """\
Write catalog copy for a course titled "{title}".

It covers these entities, which a knowledge graph clustered together --
work from what they suggest about the course, not from what you already
know about the subject in general:
{anchor_lines}

Two sentences of marketing copy for a course catalog card. No heading, no
lists, no quotation marks around the whole thing.
"""


class ModelBlurbWriter:
    """`BlurbTextPort` over whichever chat model composition hands it.

    Takes the raw `BaseChatModel` directly rather than routing through a
    narrow adapter the way `entity_definitions.DefinitionTextPort` does --
    this module already sits in `infrastructure/`, so there is no layer above
    it that `tests/test_architecture.py` needs kept free of LangChain's
    vocabulary, and a second indirection here would cost a file without
    buying that test anything.
    """

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        """Which model wrote a blurb, for `CourseBlurbRow.model`.

        A property of the writer rather than a second return value from
        `write`: returning the name beside the text would lose it on every
        refusal, and `write` refuses often by design.

        Read defensively and falling back rather than raising, because the
        value exists only for provenance -- a local model's LangChain wrapper
        carries neither `model_name` nor `model` reliably, and a stored class
        name is worth more than an exception thrown while caching a blurb
        that was generated correctly.
        """
        return (
            getattr(self._model, "model_name", None)
            or getattr(self._model, "model", None)
            or type(self._model).__name__
        )

    async def write(self, title: str, anchors: Sequence[AreaMember]) -> str | None:
        prompt = _PROMPT.format(title=title, anchor_lines=anchor_lines(anchors))
        response = await self._model.ainvoke([HumanMessage(prompt)])
        reply = str(response.content).strip()
        if not reply:
            # Refused rather than stored as an empty blurb -- see
            # `entity_definitions`'s identical reasoning for `define()`: a
            # reader sees "no blurb yet", not a blank card that looks broken.
            return None
        if ungrounded_runs(reply, anchors):
            return None
        return reply
