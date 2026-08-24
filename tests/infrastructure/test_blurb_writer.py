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


async def test_a_title_naming_an_entity_the_cluster_does_not_hold_refuses_both():
    """The title is grounded on the same terms as the blurb. Refusing only the
    title would leave a card with grounded copy under an invented name, which
    is the more prominent of the two.

    The title here is sentence case, not Title Case, and that is the property
    under test, not an accident of phrasing. `ungrounded_runs` treats its
    input as a sentence: a Title Case reply has every word capitalised, so the
    whole title reads as one ungrounded run regardless of content, and a title
    refused *for being Title Case* would pass this test on an implementation
    that refuses every Title Case reply, grounded or not -- sentence case is
    also the only shape the prompt asks for, so it is the only shape this
    check will ever meet in production. The next test below is the companion
    this one needs: together they separate "refuses ungrounded" from
    "refuses everything", which this test alone cannot do.
    """
    writer = _writer(
        "The legacy of Captain Kirk\n"
        "Follow Zefram Cochrane and the Warp drive that changed everything."
    )

    assert await writer.write("Warp drive", ANCHORS) is None


async def test_a_sentence_case_title_that_is_invented_but_grounded_is_accepted():
    """The companion the test above needs. A title in the same sentence-case
    shape, inventing its own phrasing but naming nothing outside the anchors,
    must be accepted -- otherwise the check above could be passing because it
    refuses every title in this shape, not because it refuses ungrounded
    ones."""
    writer = _writer(
        "The story of first contact\n"
        "Follow Zefram Cochrane and the Warp drive that changed everything."
    )

    assert await writer.write("Warp drive", ANCHORS) is not None


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


async def test_an_ungrounded_name_opening_a_later_sentence_is_refused():
    """Regression: a blanket sentence-initial exemption let this straight through.

    An earlier version of `_ungrounded_runs` stripped *every* sentence's
    first word unconditionally, on the reasoning that capitalisation there is
    just English grammar. That reasoning does not hold when the model's
    second sentence opens with a bare invented name rather than an ordinary
    word -- nothing distinguished the two, so "Kirk" here was silently
    exempted and the reply was accepted. `_SENTENCE_OPENERS` is what closes
    this: "Kirk" is not on that list, so it is checked like any other run.
    """
    writer = _writer("Zefram Cochrane perfected it. Kirk later commanded the ship.")

    assert await writer.write("Warp drive", ANCHORS) is None


async def test_a_legitimate_second_sentence_opener_is_still_accepted():
    """The other direction of the same fix, so it isn't a one-way ratchet.

    Blurbs are two sentences by design, and English routinely opens a second
    sentence with an ordinary word rather than a name. If closing the hole
    above meant refusing this too, the fix would trade a false accept for a
    false refuse on nearly every real reply -- this is the test that would
    catch that trade.
    """
    writer = _writer(
        "The inventor's long journey\n"
        "Zefram Cochrane invented it. Follow the story of the Warp drive."
    )

    assert await writer.write("Warp drive", ANCHORS) is not None


async def test_a_single_word_opener_identical_to_an_ungrounded_name_is_not_caught():
    """A known false accept, disclosed rather than left for someone to find.

    `_SENTENCE_OPENERS` strips only the matched opener word before checking
    the rest of a sentence, so a sentence whose *entire* ungrounded content is
    one word identical to a list entry has nothing left in it to flag.
    "Explore" here is stripped as an ordinary imperative opener -- but if it
    were standing in for an invented name (a ship called Explore, say), this
    check cannot tell the difference, because doing so means parsing "Explore
    chronicled the frontier" (a name as the sentence's subject) apart from
    "Explore the frontier" (an imperative with no subject at all), which this
    check deliberately does not attempt.

    Tolerated rather than fixed: the four words this design already excludes
    for being name-like (`discover`, `master`, `trace`, `meet`) are the ones
    most likely to double as an invented entity, and are already gone. What
    remains (`follow`, `join`, `learn`, `explore` here) is less likely to
    stand in for a name, not impossible -- and closing this fully would mean
    either the parser above, or dropping single-word sentence openers
    entirely (Option (a), already rejected in this module's history for
    refusing ordinary two-sentence copy far more often than this accepts
    an ungrounded name).
    """
    writer = _writer(
        "The story of the frontier\n"
        "Explore chronicled the frontier. The story features the Warp drive."
    )

    assert await writer.write("Warp drive", ANCHORS) is not None
