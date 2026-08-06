"""Chunking and quoting, held to the property the rest of the design rests on.

The corpus stores text and nothing else; offsets into it are derived on demand
rather than recorded. That is only sound if chunking is total and lossless, so
most of what follows is a property test rather than an example: examples pin
the boundary *choices*, properties pin the guarantee that no choice can lose a
character or shift an offset.
"""

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_team.application.corpus_spans import Span, chunk, quote

# Deliberately nasty: astral-plane characters, combining marks, CRLF, runs of
# whitespace, and the punctuation the sentence heuristic keys on. Chunking
# indexes Python string positions, so a naive byte-oriented implementation or
# one that normalises newlines shows up here immediately.
#
# Built from multi-character fragments rather than an alphabet so that "\r\n"
# is generated as a unit -- it is the sequence a chunker is most likely to
# split or normalise, and either would be a bug.
TEXT = st.lists(
    st.sampled_from(
        [
            "a",
            "b",
            "word ",
            " ",
            "\t",
            "\n",
            "\r\n",
            "\n\n",
            "\r\n\r\n",
            ". ",
            "! ",
            "?",
            '." ',
            "é",
            "日",
            "́",
            "🙂",
        ]
    ),
    max_size=120,
).map("".join)


# --- properties -------------------------------------------------------------


@given(TEXT, st.integers(min_value=1, max_value=64))
def test_chunks_concatenate_to_the_original(text: str, target: int) -> None:
    """The load-bearing property: with no overlap, chunking is a partition.

    Every offset a citation carries is an offset into the original text, so a
    chunker that drops a trailing newline or trims whitespace does not merely
    look untidy -- it silently shifts every span after the loss.
    """
    assert "".join(span.text for span in chunk(text, target_chars=target)) == text


@given(TEXT, st.integers(min_value=1, max_value=64), st.integers(min_value=0, max_value=32))
def test_every_span_text_matches_its_offsets(text: str, target: int, overlap: int) -> None:
    for span in chunk(text, target_chars=target, overlap=min(overlap, target - 1)):
        assert span.text == text[span.start : span.end]


@given(TEXT, st.integers(min_value=1, max_value=64))
def test_spans_are_ordered_contiguous_and_non_overlapping(text: str, target: int) -> None:
    spans = chunk(text, target_chars=target)
    if not spans:
        return
    assert spans[0].start == 0
    assert spans[-1].end == len(text)
    for earlier, later in pairwise(spans):
        assert earlier.end == later.start


@given(TEXT, st.integers(min_value=1, max_value=64))
def test_every_chunk_makes_progress(text: str, target: int) -> None:
    """A zero-length chunk would mean a boundary search that failed to advance,
    which is the shape a chunking loop hangs in."""
    assert all(span.end > span.start for span in chunk(text, target_chars=target))


@given(
    TEXT,
    st.integers(min_value=-50, max_value=500),
    st.integers(min_value=-50, max_value=500),
    st.integers(min_value=0, max_value=50),
)
def test_quote_never_raises_and_always_agrees_with_its_offsets(
    text: str, start: int, end: int, context: int
) -> None:
    span = quote(text, start, end, context=context)
    assert 0 <= span.start <= span.end <= len(text)
    assert span.text == text[span.start : span.end]


@given(TEXT, st.integers(min_value=1, max_value=64))
def test_chunking_is_deterministic(text: str, target: int) -> None:
    """No event records spans, so a second run must agree with the first."""
    assert chunk(text, target_chars=target) == chunk(text, target_chars=target)


# --- chunking examples ------------------------------------------------------


def test_empty_text_yields_no_chunks() -> None:
    assert chunk("") == []


def test_text_shorter_than_the_target_is_one_chunk() -> None:
    assert chunk("Short enough.", target_chars=100) == [Span(0, 13, "Short enough.")]


def test_a_paragraph_break_is_preferred_and_stays_with_the_earlier_chunk() -> None:
    """The blank line belongs to the paragraph it ends, so that the next chunk
    starts on the first character a reader would call the next paragraph."""
    text = "Alpha beta gamma.\n\nDelta epsilon zeta."
    spans = chunk(text, target_chars=25)
    assert [span.text for span in spans] == ["Alpha beta gamma.\n\n", "Delta epsilon zeta."]


def test_a_sentence_boundary_is_used_when_no_paragraph_break_fits() -> None:
    text = "One two three. Four five six. Seven eight nine."
    spans = chunk(text, target_chars=20)
    assert [span.text for span in spans] == [
        "One two three. ",
        "Four five six. ",
        "Seven eight nine.",
    ]


def test_closing_punctuation_after_the_stop_stays_with_the_sentence() -> None:
    text = 'He said "yes." Then he left the room entirely.'
    spans = chunk(text, target_chars=20)
    assert spans[0].text == 'He said "yes." '


def test_a_long_run_without_punctuation_breaks_on_a_word_boundary() -> None:
    text = "alpha bravo charlie delta echo foxtrot golf hotel"
    spans = chunk(text, target_chars=20)
    assert all(not span.text.strip().startswith(("harlie", "elta")) for span in spans)
    assert [span.text for span in spans] == [
        "alpha bravo charlie ",
        "delta echo foxtrot ",
        "golf hotel",
    ]


def test_a_word_longer_than_the_target_is_hard_split() -> None:
    """There is no clean boundary to find, and refusing to split would let one
    pathological token defeat the size bound entirely."""
    spans = chunk("x" * 25, target_chars=10)
    assert [span.text for span in spans] == ["x" * 10, "x" * 10, "x" * 5]


def test_crlf_paragraph_breaks_are_recognised_without_rewriting_the_text() -> None:
    text = "Alpha beta gamma.\r\n\r\nDelta epsilon zeta."
    spans = chunk(text, target_chars=25)
    assert spans[0].text == "Alpha beta gamma.\r\n\r\n"
    assert "".join(span.text for span in spans) == text


def test_a_long_run_of_whitespace_does_not_produce_an_empty_chunk() -> None:
    text = "alpha" + " " * 60 + "omega"
    spans = chunk(text, target_chars=10)
    assert all(span.text for span in spans)
    assert "".join(span.text for span in spans) == text


def test_overlap_repeats_the_tail_of_the_previous_chunk() -> None:
    text = "abcdefghijklmnopqrstuvwxyz"
    spans = chunk(text, target_chars=10, overlap=3)
    assert spans[0] == Span(0, 10, "abcdefghij")
    assert spans[1].start == 7
    assert spans[1].text.startswith("hij")
    assert spans[-1].end == len(text)


def test_overlap_still_covers_every_character() -> None:
    text = "abcdefghijklmnopqrstuvwxyz"
    spans = chunk(text, target_chars=10, overlap=4)
    covered = {index for span in spans for index in range(span.start, span.end)}
    assert covered == set(range(len(text)))


def test_a_target_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="target_chars"):
        chunk("anything", target_chars=0)


def test_an_overlap_that_would_stall_the_loop_is_rejected() -> None:
    """An overlap at or above the target rewinds at least as far as the chunk
    advanced, which is an infinite loop rather than a bad result."""
    with pytest.raises(ValueError, match="overlap"):
        chunk("anything", target_chars=10, overlap=10)


# --- quoting examples -------------------------------------------------------


def test_quote_returns_the_exact_span() -> None:
    text = "Alpha beta gamma."
    assert quote(text, 6, 10) == Span(6, 10, "beta")


def test_quote_clamps_rather_than_raising() -> None:
    """Offsets reach this from a model's output, where they are a guess. A
    clamp yields something a human can still judge; an exception yields a
    stack trace in the middle of a turn."""
    text = "Alpha beta."
    assert quote(text, -20, 500) == Span(0, 11, text)


def test_quote_with_reversed_offsets_collapses_to_a_point() -> None:
    assert quote("Alpha beta.", 8, 3) == Span(8, 8, "")


def test_quote_widens_by_context_on_both_sides() -> None:
    text = "Alpha beta gamma."
    assert quote(text, 6, 10, context=3) == Span(3, 13, "ha beta ga")


def test_quote_context_clamps_at_the_edges() -> None:
    text = "Alpha."
    assert quote(text, 0, 5, context=99) == Span(0, 6, "Alpha.")
