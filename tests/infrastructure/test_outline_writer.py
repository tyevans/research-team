"""Outline generation, and the shape checks a reply must pass to be stored.

Used to also pin a capitalisation-based grounding check shared with the
blurb writer, dropped 2026-08-23 -- see
`research_team/infrastructure/knowledge/anchors.py`'s module docstring for
why. What is tested here now: a shape to parse, and a floor and a ceiling on
how many sections count as an outline.
"""

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.outline_writer import ModelOutlineWriter

ANCHORS = (
    AreaMember(entity_id="1", name="Warp drive", entity_type="concept", centrality=3.0),
    AreaMember(entity_id="2", name="Zefram Cochrane", entity_type="person", centrality=2.0),
)


def _writer(text: str) -> ModelOutlineWriter:
    return ModelOutlineWriter(FakeMessagesListChatModel(responses=[AIMessage(content=text)]))


def _sections(count: int) -> str:
    """`count` well-formed, fully grounded sections."""
    return "\n\n".join(
        f"## Warp drive, part {n}\nZefram Cochrane built it." for n in range(count)
    )


GROUNDED = "Follow the Warp drive from its first flight.\n\n" + _sections(4)


async def test_an_outline_grounded_in_its_anchors_is_returned():
    outline = await _writer(GROUNDED).write("Warp drive", ANCHORS)

    assert outline is not None
    assert outline.promise == "Follow the Warp drive from its first flight."
    assert len(outline.sections) == 4
    assert outline.sections[0] == ("Warp drive, part 0", "Zefram Cochrane built it.")


async def test_an_outline_with_fewer_than_three_sections_is_refused():
    """Two sections is a blurb with bullets. The floor is what makes this a
    different artifact from the one already on the card."""
    reply = "Follow the Warp drive from its first flight.\n\n" + _sections(2)

    assert await _writer(reply).write("Warp drive", ANCHORS) is None


async def test_an_outline_with_more_than_six_sections_is_truncated_not_refused():
    """The ceiling is padding, not ungroundedness -- the extra sections are
    usually real and simply thin. Truncating keeps the good ones; refusing
    would throw away a whole model call over a formatting excess."""
    reply = "Follow the Warp drive from its first flight.\n\n" + _sections(9)

    outline = await _writer(reply).write("Warp drive", ANCHORS)

    assert outline is not None
    assert len(outline.sections) == 6
    assert outline.sections[-1][0] == "Warp drive, part 5"


async def test_a_reply_that_is_not_the_expected_shape_is_refused_rather_than_raising():
    """A local model returns prose instead of the asked-for structure often
    enough that this is the ordinary path, not the edge case."""
    reply = "Warp drive is a fine subject and here is a paragraph about it instead."

    assert await _writer(reply).write("Warp drive", ANCHORS) is None


async def test_a_heading_with_no_paragraph_under_it_refuses_the_whole_outline():
    """Half a section is a parse failure, not a section to drop quietly:
    storing one puts a heading on screen with nothing beneath it, which reads
    as a rendering bug rather than as missing copy.

    The input separates that rule from the other candidate. An earlier
    version of this test used three headings of which two were empty, and
    that reply answers `None` under *both* rules -- refuse-the-whole-outline
    returns `None`, and drop-the-empty-sections leaves one section, which is
    below `MIN_SECTIONS` and also returns `None`. It pinned nothing.
    Four sound sections plus one empty heading is the input that tells them
    apart: refuse-whole gives `None`, drop-empty would give a valid
    four-section outline. Found in review on 2026-08-23.
    """
    reply = (
        "Follow the Warp drive from its first flight.\n\n" + _sections(4) + "\n\n## Warp drive"
    )

    assert await _writer(reply).write("Warp drive", ANCHORS) is None


async def test_a_dangling_heading_past_the_ceiling_cannot_refuse_the_outline():
    """The parse's veto stops at the ceiling, and this is where that is decided.

    Fails on the version this replaced, where `_parse` applied the
    empty-summary veto to every heading it found: six sound sections followed
    by one stray `##` answered `None`. A model that runs out of budget
    mid-reply stops after a heading, so that stray line is the commonest way
    for a reply to end badly -- and it is precisely the trailing padding
    `MAX_SECTIONS` exists to absorb. Letting it destroy six sections is the
    ceiling's own argument ("text no reader will see should not be able to
    veto text every reader will") run backwards.

    The sibling above is what keeps this from becoming a blanket tolerance:
    an empty heading *inside* the ceiling still refuses.
    """
    reply = (
        "Follow the Warp drive from its first flight.\n\n" + _sections(6) + "\n\n## Dangling"
    )

    outline = await _writer(reply).write("Warp drive", ANCHORS)

    assert outline is not None
    assert len(outline.sections) == 6


async def test_a_summary_written_as_two_paragraphs_is_stored_as_one():
    """Documented in `_parse` and asserted nowhere until review asked.

    A paragraph break inside a section summary is not a distinction a catalog
    card renders, so joining with a space is the right call -- but a rule that
    lives only in a docstring is a rule nothing defends.
    """
    reply = (
        "Follow the Warp drive from its first flight.\n\n"
        "## Warp drive\nZefram Cochrane built it.\n\nWarp drive followed.\n\n" + _sections(3)
    )

    outline = await _writer(reply).write("Warp drive", ANCHORS)

    assert outline is not None
    assert outline.sections[0][1] == "Zefram Cochrane built it. Warp drive followed."


async def test_a_reply_with_sections_but_no_promise_is_refused():
    """The promise is the line the card shows; an outline without one is not
    the artifact that was asked for."""
    assert await _writer(_sections(4)).write("Warp drive", ANCHORS) is None


async def test_an_empty_reply_is_refused_rather_than_raising():
    assert await _writer("   ").write("Warp drive", ANCHORS) is None


async def test_the_model_name_is_answered_for_a_model_carrying_neither_attribute():
    """`CourseOutlineRow.model` has to be filled with something.

    `FakeMessagesListChatModel` carries neither `model_name` nor `model`,
    which is also true of some real local-model wrappers. The value exists
    only for provenance, so a class name is worth more than an exception
    raised while caching an outline that generated correctly.
    """
    assert _writer(GROUNDED).model_name


async def test_the_blurb_writer_answers_a_model_name_too():
    """Both text ports carry the property, because both rows have the column.

    Here rather than in `test_blurb_writer.py` so that the two halves of one
    decision are read together; that file is the regression net for the
    grounding move and is deliberately unedited.
    """
    from research_team.infrastructure.knowledge.blurb_writer import ModelBlurbWriter

    writer = ModelBlurbWriter(FakeMessagesListChatModel(responses=[AIMessage(content="x")]))

    assert writer.model_name
