"""`MarkdownAwareDocumentChunker`: do the offsets it reports mean what discovery reads them as?

The pairing CLAUDE.md names as the one that never gets checked -- a `Protocol`
in `application/` with exactly one adapter in `infrastructure/`. `verify_classes`
is tested against `DocumentChunk`s a test wrote by hand, and this adapter is the
only thing that ever builds a real one, so nothing else asks whether the two
agree. Every test here drives the real chunker and then reads its output through
the real translation.

The property under test is not "chunks were produced". It is that
`chunk.text[:len(prefix)]` is a header the document really holds at
`prefix_start_char`, and that `chunk.text[len(prefix):]` is the document
verbatim at `start_char`. Both are silent when wrong: a citation resolves,
renders, and quotes the wrong words.
"""

from research_team.application.ontology_discovery import verify_classes
from research_team.infrastructure.knowledge.ontology_chunker import (
    MarkdownAwareDocumentChunker,
)

HEADER = "| Rank | Reward |\n|---|---|\n"

# Long enough that a 400-character chunk cuts the table several times, and
# prefixed with prose so the table does not start at offset 0 -- a table at 0
# makes an untranslated header offset accidentally correct.
DOCUMENT = (
    "Ranks are awarded at the end of a stage. " * 8
    + "\n\n"
    + HEADER
    + "".join(
        f"| {letter} rank | {index * 50} coins |\n" for index, letter in enumerate("SABCDEF")
    )
)

# A second table with the same column layout, further down. Without it a
# backwards search and a forwards search for the header are indistinguishable.
DOCUMENT += "\n\nA later table repeats the layout.\n\n" + HEADER + "| X rank | 0 coins |\n"


def _chunker() -> MarkdownAwareDocumentChunker:
    return MarkdownAwareDocumentChunker(chunk_chars=200, overlap_chars=40)


def test_every_chunk_is_its_prefix_plus_the_document_at_its_offset():
    """The invariant the whole translation rests on, asserted over a real cut
    rather than assumed. `MarkdownTableChunker` documents it as
    `chunk.text[prefix:] == original[start_char:end_char]`; this is the same
    statement in `DocumentChunk`'s own vocabulary, and it is what fails if the
    adapter ever slices `prefix` off the wrong end of the text.
    """
    chunks = _chunker().chunk(DOCUMENT)

    assert len(chunks) > 3
    for chunk in chunks:
        body = chunk.text[len(chunk.prefix) :]
        assert DOCUMENT[chunk.start_char : chunk.start_char + len(body)] == body


def test_a_prefixed_chunk_reports_where_its_header_really_is():
    """`MarkdownTableChunker` records the header's *text* and not its offset,
    so the adapter searches for it -- and searching forwards instead of
    backwards finds the second table's identical header on this document.
    Fails on a forwards search, which is why the fixture has two tables.
    """
    prefixed = [chunk for chunk in _chunker().chunk(DOCUMENT) if chunk.prefix]

    assert prefixed
    for chunk in prefixed:
        assert DOCUMENT[chunk.prefix_start_char :].startswith(chunk.prefix)
        assert chunk.prefix_start_char < chunk.start_char


def test_a_class_named_by_a_repeated_header_cites_the_document_correctly():
    """Both ends over real data: the real chunker's output goes through the
    real `verify_classes`, and the span comes back pointing at the header the
    document actually holds.

    The model's offsets here are into the chunk (0 to the header's length),
    which is what a model shown `chunk.text` answers. Untranslated they would
    land in the opening prose, which is inside the document and reads as a
    plausible citation.
    """
    chunk = next(chunk for chunk in _chunker().chunk(DOCUMENT) if chunk.prefix)
    member = chunk.text[len(chunk.prefix) :].split("|")[1].strip()
    proposals = [
        {
            "name": "Rank",
            "kind": "ordered_scale",
            "evidence": {"start": 0, "end": len("| Rank | Reward |")},
            "members": [{"name": member}],
        }
    ]

    verified = verify_classes(
        proposals, document_text=DOCUMENT, source_id="ranks", chunk=chunk
    )

    span = verified[0].evidence
    assert DOCUMENT[span.start : span.end] == "| Rank | Reward |"
    assert verified[0].members[0].name == member


def test_a_chunk_of_prose_carries_no_prefix_and_translates_by_its_offset():
    """The ordinary case, and the one a translation bug would leave working.
    An untranslated span is right only when `start_char` is 0, so this asserts
    against a chunk that starts somewhere else.
    """
    plain = [
        chunk
        for chunk in _chunker().chunk(DOCUMENT)
        if not chunk.prefix and chunk.start_char > 0
    ]

    assert plain
    chunk = plain[0]
    proposals = [
        {
            "name": "Stage",
            "kind": "unordered_set",
            "evidence": {"start": 0, "end": 10},
            "members": [{"name": chunk.text[:6]}],
        }
    ]

    verified = verify_classes(
        proposals, document_text=DOCUMENT, source_id="ranks", chunk=chunk
    )

    span = verified[0].evidence
    assert (span.start, span.end) == (chunk.start_char, chunk.start_char + 10)
