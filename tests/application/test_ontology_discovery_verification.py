"""Discovery's pure half: what the model is asked, and what is believed back."""

from research_team.knowledge.application.ontology_discovery import (
    build_prompt,
    parse_ontology,
    verify_classes,
)

SONGS = (
    "There are six difficulties available in the game: EASY, NORMAL, HARD, "
    "EXPERT, MASTER, and APPEND. Achieving combo milestones grants coins."
)


def test_the_prompt_carries_the_document_and_forbids_outside_knowledge():
    prompt = build_prompt(SONGS)

    assert SONGS in prompt
    assert "outside the document" in prompt


def test_the_prompt_asks_for_the_quoted_sentence_rather_than_its_offsets():
    """The prompt is where this change actually lives. `_span` can locate a
    quote all it likes; if the prompt still asks for `{"start": ..., "end":
    ...}` the model keeps answering with offsets and every class is refused.

    Both halves are asserted, because either alone is passable by a prompt that
    asks for both and gets the old shape half the time. Measured against
    `qwen3.8-27b-64k-txt` on 2026-08-24, both wordings over the same 12 chunks
    of five real corpus documents: the offsets wording produced 15 stored
    citations of which **1** pointed at text naming the class or a member; this
    wording produced 14, of which **13** did. The wording is the whole of that
    difference -- `verify_classes` is unchanged between the two arms.
    """
    prompt = build_prompt(SONGS)

    assert "copied from\n    the document exactly as it appears" in prompt
    assert "character offsets" not in prompt


def test_the_prompt_rules_out_open_lists_and_bare_contrasts():
    """Measured 2026-08-15 in `wiki-roman-economy`: "attested for a wide range
    of occupations, including fishermen..." names nine members against a
    declared 268. A class built from it asserts Rome had nine occupations.

    A prompt-content assertion is weak on its own -- a schema shapes prompts
    and does not enforce output -- so this is the first half of the defence,
    not the whole of it. The second half is `declared_count`: `9 of 268` reads
    as a sample on sight, which is what the view renders.
    """
    prompt = build_prompt(SONGS)

    assert "including" in prompt
    assert "Official cults" in prompt


def test_a_fenced_reply_is_read_anyway():
    """ "Answer with JSON and nothing else" is followed most of the time and
    not all of it -- the same tolerance `entity_definitions._parse` needs."""
    raw = (
        '```json\n{"classes": [{"name": "Difficulty", "kind": "unordered_set", '
        '"members": [{"name": "EASY"}]}]}\n```'
    )

    assert parse_ontology(raw)[0]["name"] == "Difficulty"


def test_an_unreadable_reply_is_None_not_an_empty_list():
    """`None` and `[]` are different answers and the service acts differently
    on each, so the parser has to return different things.

    `[]` is the model saying "no classes here", which records the document as
    examined and takes it off the sweep. `None` is a reply nobody could read,
    which must leave the document on the sweep -- otherwise one transient
    failure marks it permanently done and nobody ever retries it. Collapsing
    the two into `[]` is the bug this signature exists to prevent.
    """
    assert parse_ontology("I'm afraid I can't do that.") is None


def test_an_empty_answer_is_readable_and_says_there_are_no_classes():
    assert parse_ontology('{"classes": []}') == []


def test_a_member_that_is_not_in_the_document_is_rejected_with_its_reason():
    """The pass's main defence against a model pattern-matching a plausible
    taxonomy onto a document that does not state one. An invented class looks
    exactly like a discovered one, so the check has to be against the text.

    Both halves are asserted: the member is gone from `members`, AND it is
    named in `rejected_members`. An implementation that drops it silently
    passes the first half alone and leaves the class unjudgeable -- the reader
    sees a short class and cannot tell an invented member from a document
    genuinely missing one.
    """
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "declared_count": 6,
            "evidence": "There are six difficulties available in the game",
            "members": [{"name": "EASY", "ordinal": 0}, {"name": "LEGEND", "ordinal": 6}],
        }
    ]

    (klass,) = verify_classes(proposals, document_text=SONGS, source_id="songs")

    assert [member.name for member in klass.members] == ["EASY"]
    assert klass.rejected_members[0].name == "LEGEND"
    assert "not found" in klass.rejected_members[0].reason


def test_evidence_the_document_does_not_contain_drops_the_class_whole():
    """A quote the document does not hold is a sentence the model wrote rather
    than read, and a class nobody can open the source for is exactly the
    unjudgeable artefact this feature exists to avoid. Dropping the class is
    right where dropping a member is not: without evidence there is nothing
    left to judge, so recording it would record something uncheckable.

    The quote is a near-miss on purpose -- `SONGS` says "six", this says
    "seven" -- because that is what a fabrication looks like. A quote sharing
    no words with the document would pass an implementation that only checked
    the evidence was a non-empty string.
    """
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": "There are seven difficulties available in the game",
            "members": [{"name": "EASY"}],
        }
    ]

    assert verify_classes(proposals, document_text=SONGS, source_id="songs") == []


WRAPPED = (
    "The agent answering that page may write an mcq, cloze, or flashcard component\n"
    "into its reply instead of just prose, and the block renders live."
)
"""A hard-wrapped sentence, which is what killed the only real class this pass
ever found on the owner's corpus. Measured 2026-08-24: the model quoted it as a
reader sees it, with the line break flattened to a space, so `str.find` did not
hold it and `interactive components` {mcq, cloze, flashcard} -- all three
members present verbatim -- was dropped whole. The newline is the fixture."""

FLATTENED = (
    "The agent answering that page may write an mcq, cloze, or flashcard component "
    "into its reply instead of just prose"
)


def test_a_quote_the_document_wraps_is_still_refused_by_the_strict_pass():
    """The strict default is unchanged, and this is the assertion that says so.

    It is also the case that *distinguishes* the two settings: a fixture whose
    quote is findable passes under strict and lenient alike and would prove
    nothing about either. The whole difference between the settings is what
    happens to this input, so it is the input both tests are written on.
    """
    proposals = [
        {
            "name": "interactive components",
            "kind": "unordered_set",
            "evidence": FLATTENED,
            "members": [{"name": "mcq"}, {"name": "cloze"}, {"name": "flashcard"}],
        }
    ]

    assert verify_classes(proposals, document_text=WRAPPED, source_id="readme") == []


def test_the_lenient_pass_keeps_that_class_and_cites_a_member_instead():
    """What `strict=False` buys, on the document that motivated it.

    Three assertions and none is redundant: the class survives, its span is the
    first member's own occurrence rather than anything near the absent quote,
    and `evidence_quoted` says so. Without the third a lenient class is
    indistinguishable on read from one whose sentence was located, which is the
    silence this lever would otherwise add rather than remove.
    """
    proposals = [
        {
            "name": "interactive components",
            "kind": "unordered_set",
            "evidence": FLATTENED,
            "members": [{"name": "mcq"}, {"name": "cloze"}, {"name": "flashcard"}],
        }
    ]

    (klass,) = verify_classes(
        proposals, document_text=WRAPPED, source_id="readme", strict=False
    )

    assert [member.name for member in klass.members] == ["mcq", "cloze", "flashcard"]
    assert WRAPPED[klass.evidence.start : klass.evidence.end] == "mcq"
    assert klass.evidence_quoted is False


def test_a_lenient_pass_still_refuses_a_class_whose_members_are_all_invented():
    """Lenient drops one gate, not both. A class that keeps no member has
    nothing left in the document at all -- no quote and no name -- so there is
    no honest span to cite and nothing for a reader to open.

    Proved red by removing the `if not members: continue` guard, which is the
    only line standing between this and a class cited at offset 0.
    """
    proposals = [
        {
            "name": "interactive components",
            "kind": "unordered_set",
            "evidence": FLATTENED,
            "members": [{"name": "carousel"}, {"name": "slider"}],
        }
    ]

    assert (
        verify_classes(proposals, document_text=WRAPPED, source_id="readme", strict=False)
        == []
    )


def test_a_lenient_pass_still_marks_a_located_quote_as_quoted():
    """The flag tracks the span, not the setting. A lenient sweep finds mostly
    ordinary classes, and marking those doubtful because of the setting they
    were found under would make the flag useless for the thing it exists for --
    telling the two populations apart afterwards.
    """
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": "There are six difficulties available in the game",
            "members": [{"name": "EASY", "ordinal": 0}],
        }
    ]

    (klass,) = verify_classes(proposals, document_text=SONGS, source_id="songs", strict=False)

    assert klass.evidence_quoted is True
    assert SONGS[klass.evidence.start : klass.evidence.end].startswith("There are six")


def test_evidence_given_as_character_offsets_is_refused():
    """The shape the prompt asked for until 2026-08-24, kept as a test rather
    than as a code path. A live model handed the new prompt still answers with
    the old shape occasionally, and accepting it would re-admit the guessed
    offsets this change exists to stop trusting -- once stored, a class cited
    from an estimate is indistinguishable from one cited from a quote.

    Fails on any `_span` that keeps a dict branch. `{"start": 0, "end": 66}` is
    a range that really does lie inside `SONGS`, so an implementation that
    bounds-checks it verifies happily.
    """
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": {"start": 0, "end": 66},
            "members": [{"name": "EASY"}],
        }
    ]

    assert verify_classes(proposals, document_text=SONGS, source_id="songs") == []


def test_a_class_with_no_surviving_members_is_dropped():
    """A class name with nothing in it is not a discovery."""
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": "There are six difficulties available in the game",
            "members": [{"name": "LEGEND"}],
        }
    ]

    assert verify_classes(proposals, document_text=SONGS, source_id="songs") == []


def test_an_unknown_kind_is_refused_rather_than_coerced():
    """`kind` selects the whole rendering. Defaulting a misread value to
    `unordered_set` would be survivable; defaulting it to anything would turn a
    misread into a claim about the text, and an `ordered_scale` asserts an
    ordering the document may never have stated."""
    proposals = [
        {
            "name": "Difficulty",
            "kind": "spectrum",
            "evidence": "There are six difficulties available in the game",
            "members": [{"name": "EASY"}],
        }
    ]

    assert verify_classes(proposals, document_text=SONGS, source_id="songs") == []


def test_the_stored_span_is_the_range_the_quoted_sentence_actually_occupies():
    """The span is what makes a class judgeable: the view opens the source
    document at these offsets. A class carrying members and no usable span
    renders as an assertion with no way to check it.

    This is the test that separates locating a quote from believing an offset.
    The sentence quoted does **not** start at 0 -- it is the second sentence of
    `SONGS` -- so the assertion is that the stored range slices back to exactly
    the quote, byte for byte, rather than to something that merely overlaps it.
    An implementation reading offsets off the model would have no offsets here
    at all and drop the class; one that located the quote and then rounded to a
    sentence boundary would fail the equality.
    """
    quote = "Achieving combo milestones grants coins."
    assert not SONGS.startswith(quote)
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": quote,
            "members": [{"name": "EASY", "ordinal": 0}],
        }
    ]

    (klass,) = verify_classes(proposals, document_text=SONGS, source_id="songs")

    assert klass.evidence.source_id == "songs"
    assert SONGS[klass.evidence.start : klass.evidence.end] == quote


def test_a_declared_count_the_members_fall_short_of_is_kept_not_repaired():
    """The 9-of-268 case, measured in `wiki-roman-economy` on 2026-08-15.

    Verification does not reconcile the two numbers and does not drop the
    class at some ratio threshold -- a threshold would be a number nobody
    could justify, and a reader sees `9 of 268` for what it is faster than any
    rule could classify it. Both numbers survive to the view.
    """
    proposals = [
        {
            "name": "Difficulty",
            "kind": "unordered_set",
            "declared_count": 268,
            "evidence": "There are six difficulties available in the game",
            "members": [{"name": "EASY"}],
        }
    ]

    (klass,) = verify_classes(proposals, document_text=SONGS, source_id="songs")

    assert klass.declared_count == 268
    assert len(klass.members) == 1


def test_a_reply_that_is_a_list_rather_than_an_object_is_unreadable():
    """Not defensive padding: "answer with JSON" invites a bare array often
    enough, and `payload.get` on a list raises rather than returning None.

    `None` rather than `[]` -- a bare array is a reply that did not answer the
    question asked, not a reply saying the document states no classes."""
    assert parse_ontology('[{"name": "Difficulty"}]') is None
