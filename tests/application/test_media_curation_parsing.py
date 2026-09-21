"""Tests for parsing model responses in the media curation pipeline.

Mirrors `tests/application/test_ontology_discovery.py`'s treatment of
`_members_from` -- each parser is exercised for a dropped-and-counted item, a
prose reply that yields nothing, and the per-topic/per-need cap.
"""

import json

from research_team.application.research.media_curation import (
    MAX_CANDIDATES_PER_NEED,
    MAX_NEEDS_PER_TOPIC,
    MAX_QUERIES_PER_NEED,
    parse_judgements,
    parse_needs,
    parse_terms,
)


def _need(i: int) -> dict:
    return {"medium": "image", "description": f"need {i}", "why": "because"}


def _term(i: int) -> dict:
    return {"text": f"query {i}", "categories": "images"}


def _judgement(i: int) -> dict:
    return {"index": i, "keep": True, "reason": f"reason {i}"}


def test_parse_needs_drops_an_item_missing_its_description_and_counts_it():
    needs, rejected = parse_needs(
        json.dumps(
            [
                {"medium": "image", "description": "", "why": "x"},
                {"medium": "image", "description": "A map", "why": "y"},
            ]
        )
    )
    assert [n.description for n in needs] == ["A map"]
    assert rejected == 1


def test_parse_needs_returns_nothing_for_prose_instead_of_json():
    """A model that answers in prose is a legitimate outcome, not an error:
    a topic can genuinely want no imagery, and a parser that raised would
    make the chain fail where it should return nothing.

    This would still pass if `parse_needs` raised and the test caught the
    exception instead of asserting `== []` -- what pins the no-raise
    behaviour is that the call above is unguarded.

    The count is 1, not 0, and that changed on 2026-08-16: prose is a reply
    nobody could read, which is a different fact about the run from a model
    that read the topic and said "nothing here". Both still yield no needs,
    so no caller's control flow depends on which happened -- see
    `test_parse_needs_separates_an_unreadable_reply_from_an_empty_one`.
    """
    needs, rejected = parse_needs("I don't think this topic needs images.")
    assert needs == []
    assert rejected == 1


def test_parse_needs_separates_an_unreadable_reply_from_an_empty_one():
    """The distinction the three parsers exist to preserve, pinned once.

    An empty array is the model answering the question with "none"; prose is
    the model not answering it. Both produce no needs. Only the count tells
    them apart, and until 2026-08-16 it did not -- a real run reported two
    needs and zero candidates with `rejected_parses` at 0, and which stage
    had failed could not be recovered from the response at all.

    Fails if either parser branch is deleted: dropping the `items is None`
    guard makes prose report 0, and counting `[]` as a rejection makes the
    empty case report 1.
    """
    assert parse_needs("[]") == ([], 0)
    assert parse_needs("not json at all") == ([], 1)
    assert parse_terms("[]") == ([], 0)
    assert parse_terms("no terms come to mind") == ([], 1)
    assert parse_judgements("[]") == ([], 0)
    assert parse_judgements("none of these work") == ([], 1)


def test_parse_needs_honours_the_cap():
    needs, _ = parse_needs(json.dumps([_need(i) for i in range(10)]))
    assert len(needs) == MAX_NEEDS_PER_TOPIC


def test_parse_terms_drops_an_item_missing_its_text_and_counts_it():
    queries, rejected = parse_terms(
        json.dumps(
            [
                {"text": "", "categories": "images"},
                {"text": "roman forum ruins", "categories": "images"},
            ]
        )
    )
    assert [q.text for q in queries] == ["roman forum ruins"]
    assert rejected == 1


def test_parse_terms_returns_nothing_for_prose_instead_of_json():
    """Same legitimate-empty-outcome reasoning as `parse_needs`: a need can
    genuinely suggest no searchable term, and this must not raise for it.

    Counted as one unreadable reply -- see `parse_needs`' prose test."""
    queries, rejected = parse_terms("No good search terms come to mind.")
    assert queries == []
    assert rejected == 1


def test_parse_terms_honours_the_cap():
    queries, _ = parse_terms(json.dumps([_term(i) for i in range(10)]))
    assert len(queries) == MAX_QUERIES_PER_NEED


def test_parse_judgements_drops_an_item_missing_its_index_and_counts_it():
    judgements, rejected = parse_judgements(
        json.dumps(
            [
                {"keep": True, "reason": "no index"},
                {"index": 0, "keep": True, "reason": "the clearest of the three"},
            ]
        )
    )
    assert [j.reason for j in judgements] == ["the clearest of the three"]
    assert rejected == 1


def test_parse_judgements_returns_nothing_for_prose_instead_of_json():
    """A judge that keeps none of the pooled results is legitimate -- the
    search returned nothing worth proposing -- and must not raise.

    Counted as one unreadable reply -- see `parse_needs`' prose test. A judge
    that genuinely keeps nothing answers `[]` or a list of `keep: false`
    verdicts, neither of which is counted here."""
    judgements, rejected = parse_judgements("None of these results are usable.")
    assert judgements == []
    assert rejected == 1


def test_parse_judgements_drops_items_the_model_marked_keep_false():
    """A `keep: false` verdict is not malformed -- it is the judge doing its
    job -- so it must not be counted as a rejection the way a missing field
    is. This would pass if `parse_judgements` ignored `keep` entirely and
    returned every well-formed item; what it pins is that the survivors are
    exactly the kept ones."""
    judgements, rejected = parse_judgements(
        json.dumps(
            [
                {"index": 0, "keep": False, "reason": "duplicate of index 1"},
                {"index": 1, "keep": True, "reason": "clear and on topic"},
            ]
        )
    )
    assert [j.index for j in judgements] == [1]
    assert rejected == 0


def test_parse_judgements_honours_the_cap():
    judgements, _ = parse_judgements(json.dumps([_judgement(i) for i in range(10)]))
    assert len(judgements) == MAX_CANDIDATES_PER_NEED


def test_parse_needs_accepts_the_keyed_form_identically_to_the_bare_array():
    """Models wrap lists in a keyed object routinely, and `ontology_discovery.py`
    asks for exactly that shape -- a parser that only reads a bare array turns
    a perfectly good answer into "no needs", indistinguishable from the model
    genuinely declining. This would pass if `parse_needs` accepted only the
    bare-array form and this test fed it one; it feeds the keyed form instead,
    so it is red until the parser reads both."""
    bare = parse_needs(json.dumps([_need(0), _need(1)]))
    keyed = parse_needs(json.dumps({"needs": [_need(0), _need(1)]}))
    assert [n.description for n in keyed[0]] == [n.description for n in bare[0]]
    assert keyed[1] == bare[1]


def test_parse_terms_accepts_the_keyed_form_identically_to_the_bare_array():
    bare = parse_terms(json.dumps([_term(0), _term(1)]))
    keyed = parse_terms(json.dumps({"queries": [_term(0), _term(1)]}))
    assert [q.text for q in keyed[0]] == [q.text for q in bare[0]]
    assert keyed[1] == bare[1]


def test_parse_judgements_accepts_the_keyed_form_identically_to_the_bare_array():
    bare = parse_judgements(json.dumps([_judgement(0), _judgement(1)]))
    keyed = parse_judgements(json.dumps({"judgements": [_judgement(0), _judgement(1)]}))
    assert [j.index for j in keyed[0]] == [j.index for j in bare[0]]
    assert keyed[1] == bare[1]
