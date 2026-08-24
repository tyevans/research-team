"""Blurb generation, and the shape checks a reply must pass to be stored.

Used to also pin a capitalisation-based grounding check shared with the
outline writer, dropped 2026-08-23 -- see
`research_team/infrastructure/knowledge/anchors.py`'s module docstring for
why. The tests that pinned only that check are gone with it; what remains
here covers the title/blurb shape and the top-anchor-name refusal, neither of
which the grounding check touched.
"""

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
    writer = _writer(
        "The story of first contact\n"
        "Follow Zefram Cochrane and the Warp drive that changed everything."
    )

    assert await writer.write("Warp drive", ANCHORS) is not None


async def test_the_writer_returns_a_title_and_a_blurb_from_one_call():
    """One call, not two. A second model call for the title would double a
    sweep's cost and let the two disagree about what the course is about, with
    nothing able to notice."""
    writer = _writer(
        "The story of first contact\n"
        "Follow Zefram Cochrane and the Warp drive that changed everything."
    )

    draft = await writer.write("Warp drive", ANCHORS)

    assert draft is not None
    assert draft.title == "The story of first contact"
    assert draft.text == "Follow Zefram Cochrane and the Warp drive that changed everything."


async def test_a_reply_with_a_blurb_and_no_title_is_refused():
    writer = _writer("Follow Zefram Cochrane and the Warp drive that changed everything.")

    assert await writer.write("Warp drive", ANCHORS) is None


async def test_a_title_identical_to_the_top_anchors_name_is_refused():
    """A model handed one dominant entity returns it verbatim. That answer
    passes every grounding check by construction -- it is literally an
    anchor name -- and it is the exact defect this task exists to fix,
    wearing the shape of a correct answer."""
    writer = _writer(
        "Warp Drive\nFollow Zefram Cochrane and the Warp drive that changed everything."
    )

    assert await writer.write("Warp drive", ANCHORS) is None


async def test_a_title_identical_to_the_anchor_case_and_punctuation_insensitively_refused():
    writer = _writer(
        "warp drive!\nFollow Zefram Cochrane and the Warp drive that changed everything."
    )

    assert await writer.write("Warp drive", ANCHORS) is None


async def test_a_title_identical_to_a_multi_word_anchor_is_refused_by_the_anchor_check_alone():
    """`Warp drive` is two words, so the tests above are refused by the
    anchor-name check *and* by the word-count band at once -- nothing proves
    the anchor-name check does anything on its own. A top anchor of three or
    more words closes that gap: `United Federation of Planets` is within the
    2-8 word band, so a title identical to it can only be caught by the
    anchor-name comparison."""
    anchors = (
        AreaMember(
            entity_id="1",
            name="United Federation of Planets",
            entity_type="organization",
            centrality=3.0,
        ),
        AreaMember(
            entity_id="2", name="Zefram Cochrane", entity_type="person", centrality=2.0
        ),
    )
    writer = _writer(
        "United Federation of Planets\n"
        "Follow Zefram Cochrane as the United Federation of Planets takes shape."
    )

    assert await writer.write("United Federation of Planets", anchors) is None


async def test_an_empty_reply_is_refused_rather_than_stored_as_an_empty_blurb():
    assert await _writer("   ").write("Warp drive", ANCHORS) is None
