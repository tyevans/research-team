"""Blurb generation, and the check that keeps it inside the corpus."""

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.blurb_writer import ModelBlurbWriter

ANCHORS = (
    AreaMember(entity_id="1", name="Warp drive", entity_type="concept", centrality=3.0),
    AreaMember(entity_id="2", name="Zefram Cochrane", entity_type="person", centrality=2.0),
)


def _writer(text: str) -> ModelBlurbWriter:
    return ModelBlurbWriter(FakeMessagesListChatModel(responses=[AIMessage(content=text)]))


async def test_a_blurb_built_from_the_anchors_is_returned():
    writer = _writer("Follow Zefram Cochrane and the Warp drive that changed everything.")

    assert await writer.write("Warp drive", ANCHORS) is not None


async def test_a_blurb_naming_an_entity_the_cluster_does_not_hold_is_refused():
    """The one check available without spans.

    A model asked to write about warp drive will happily bring in Kirk from
    what it read years ago, and that copy is indistinguishable at a glance from
    copy derived from this cluster -- which is exactly why a reader would trust
    it. A blurb that names an entity the corpus did not put in this area
    promises a course the corpus cannot teach.

    Weaker than the citation check `entity_definitions` runs, and recorded as
    weaker rather than presented as equivalent.
    """
    writer = _writer("Join Captain Kirk as he explores the Warp drive.")

    assert await writer.write("Warp drive", ANCHORS) is None


async def test_an_empty_reply_is_refused_rather_than_stored_as_an_empty_blurb():
    assert await _writer("   ").write("Warp drive", ANCHORS) is None


async def test_a_legitimate_shortening_the_check_still_refuses():
    """A known false refusal, accepted deliberately.

    The check is substring-against-anchor-names, not synonym-aware. "Zefram
    Cochrane" being shortened to a bare "Cochrane" matches (it's a substring
    of the anchor name), but a plural or category term describing an anchor
    without repeating its name does not. This costs a reader a sentence of
    copy that would have been fine; the alternative -- guessing when an
    unmatched run is "close enough" -- is the thing that lets Kirk back in.

    "the Inventor" is a legitimate way to refer to Zefram Cochrane without
    repeating his name -- and the check refuses it anyway, because "Inventor"
    is a capitalised run with no anchor name to match against. That refusal
    is the cost this design accepts, not a bug to fix here.
    """
    writer = _writer("Follow the Inventor as he perfects the Warp drive.")

    assert await writer.write("Warp drive", ANCHORS) is None
