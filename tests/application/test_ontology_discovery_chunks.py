"""Chunking, multi-chunk span offset translation, and chunk merge tests."""

from research_team.application.corpus_read import StoredDocument
from research_team.application.ontology_discovery import (
    DocumentChunk,
    OntologyDiscoveryService,
    merge_classes,
    verify_classes,
)
from research_team.domain.knowledge.ontology import DiscoveredClass
from research_team.domain.research.corpus import TextRecord

SONGS = (
    "There are six difficulties available in the game: EASY, NORMAL, HARD, "
    "EXPERT, MASTER, and APPEND. Achieving combo milestones grants coins."
)
FOUND_ONE = (
    '{"classes": [{"name": "Difficulty", "kind": "ordered_scale", '
    '"declared_count": 6, "evidence": "There are six difficulties available in the game", '
    '"members": [{"name": "EASY", "ordinal": 0}]}]}'
)


class _FakeCorpus:
    """`CorpusReadPort`, narrowed to the one method discovery calls."""

    def __init__(self, documents: dict[str, str]) -> None:
        self._documents = documents

    async def read_document(self, source_id, *, include_dropped=False):
        text = self._documents.get(source_id)
        if text is None:
            return None
        return StoredDocument(
            record=TextRecord(source_id=source_id, sha256="x", char_count=len(text)),
            text=text,
        )


class _FixedChunker:
    """`DocumentChunkPort` returning chunks a test wrote out by hand.

    Deliberately not the real `MarkdownAwareDocumentChunker`: that lives in
    `infrastructure/` and the application layer may not import it. What is
    tested here is what this pass does *with* chunks, including offsets it
    could not otherwise be handed -- a chunk starting at 5,000 with a synthetic
    header from offset 12 is two lines here and a 5,000-character fixture
    otherwise.
    """

    def __init__(self, chunks):
        self.chunks = chunks

    def chunk(self, text):
        return self.chunks


class _ScriptedModel:
    """One reply per call, in order. Fewer replies than chunks is an error the
    test wants to see rather than a repeat of the last one."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


class _FakeRecorder:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, str, list]] = []

    async def record(self, source_id, model_version, classes) -> None:
        self.recorded.append((source_id, model_version, classes))


# --- Chunking: offsets, merging, and a chunk that fails ------------------
#
# The three properties the whole-document pass never had to have. Offsets are
# first because they are the one that fails silently: every untranslated span
# is inside the document, renders, and quotes words the model never read.

RANK_DOCUMENT = (
    "Rewards are given by rank.\n\n"
    "| Rank | Reward |\n"
    "|---|---|\n"
    "| S rank | 500 coins |\n"
    "| A rank | 250 coins |\n"
)
TABLE_HEADER = "| Rank | Reward |\n|---|---|\n"
HEADER_START = RANK_DOCUMENT.index(TABLE_HEADER)
ROWS_START = HEADER_START + len(TABLE_HEADER)
SECOND_ROW_START = RANK_DOCUMENT.index("| A rank |")


def _rank_chunk() -> DocumentChunk:
    """The second chunk of the table: rows only, with the header prepended.

    This is exactly what `MarkdownTableChunker` produces for a chunk that
    starts inside a table -- `text` is the header followed by document text
    that begins at `start_char`, and the header is not what the document holds
    at `start_char`.
    """
    return DocumentChunk(
        text=TABLE_HEADER + RANK_DOCUMENT[SECOND_ROW_START:],
        start_char=SECOND_ROW_START,
        prefix=TABLE_HEADER,
        prefix_start_char=HEADER_START,
    )


def test_a_class_found_in_a_later_chunk_cites_the_document_not_the_chunk():
    """The likeliest silent bug in chunking, and the reason this test names a
    chunk that is not the first: with `start_char == 0` an untranslated span
    and a translated one are the same number, so a first-chunk test proves
    nothing at all.

    `| A rank |` is at offset 28 of the *chunk*. Untranslated, offsets 28..38 of
    the document land in the header line -- a real range, inside the document,
    that renders perfectly and quotes the wrong text. Fails with the
    translation removed.

    Locating the quote does not make this test redundant: `str.find` searches
    the chunk, so it produces chunk coordinates and the translation is still
    the only thing standing between them and a wrong citation.
    """
    chunk = _rank_chunk()
    assert chunk.text.index("| A rank |") == 28
    assert RANK_DOCUMENT[28:38] == "| Rank | R"
    proposals = [
        {
            "name": "Rank",
            "kind": "ordered_scale",
            "evidence": "| A rank |",
            "members": [{"name": "A rank", "ordinal": 1}],
        }
    ]

    verified = verify_classes(
        proposals, document_text=RANK_DOCUMENT, source_id="ranks", chunk=chunk
    )

    span = verified[0].evidence
    assert (span.start, span.end) == (SECOND_ROW_START, SECOND_ROW_START + 10)
    assert RANK_DOCUMENT[span.start : span.end] == "| A rank |"


def test_a_span_inside_a_repeated_header_cites_where_the_header_really_is():
    """The case the "never chunks" reasoning said could not be served. The
    class name lives entirely in `| Rank | Reward |`, so the model's evidence
    points into text the document does not contain at the chunk's offset -- and
    a pass that dropped it would find the class and lose the sentence that
    states it.

    Shifting by `start_char` instead would push this past the header and into
    the rows; refusing it would drop the class. Both are what this fails on.
    """
    chunk = _rank_chunk()
    proposals = [
        {
            "name": "Rank",
            "kind": "ordered_scale",
            "evidence": "| Rank | Reward |",
            "members": [{"name": "A rank"}],
        }
    ]

    verified = verify_classes(
        proposals, document_text=RANK_DOCUMENT, source_id="ranks", chunk=chunk
    )

    span = verified[0].evidence
    assert RANK_DOCUMENT[span.start : span.end] == "| Rank | Reward |"


def test_a_span_straddling_the_header_and_the_rows_cites_the_header_alone():
    """No half-open range covers both: rows the model never saw sit between the
    header and this chunk's first row. The header is returned because it is the
    part that names the class and is text the model did read.

    A range from the header's start to the row's end would pass any bounds
    check and cite `| S rank | 500 coins |` -- a row that was in another chunk
    -- as evidence for this one.
    """
    chunk = _rank_chunk()
    proposals = [
        {
            "name": "Rank",
            "kind": "ordered_scale",
            "evidence": TABLE_HEADER + "| A rank |",
            "members": [{"name": "A rank"}],
        }
    ]

    verified = verify_classes(
        proposals, document_text=RANK_DOCUMENT, source_id="ranks", chunk=chunk
    )

    span = verified[0].evidence
    assert (span.start, span.end) == (HEADER_START, ROWS_START)
    assert "S rank" not in RANK_DOCUMENT[span.start : span.end]


def test_a_quote_the_chunk_holds_twice_is_cited_at_its_first_occurrence():
    """`MarkdownTableChunker` puts the header at the front of the chunk and the
    document may well repeat it further down -- a long table split into two in
    the source, or a second table with the same columns. So a header quote has
    two homes in one chunk, and which one is picked decides where the reader
    lands.

    The first is right, and it is right for a reason beyond "pick one": the
    first occurrence is the prefix, which `_to_document_span` maps to where the
    header really lives. A later occurrence is ordinary chunk text and shifts
    by `start_char`, which here would cite the *second* table -- a real range
    that renders, in a table the class was not found in.

    Fails on an implementation using `rfind`, or one scanning past the prefix.
    """
    document = (
        RANK_DOCUMENT
        + "\nAnother table follows.\n\n"
        + TABLE_HEADER
        + "| B rank | 100 coins |\n"
    )
    second_header_start = document.index(TABLE_HEADER, HEADER_START + 1)
    chunk = DocumentChunk(
        text=TABLE_HEADER + document[SECOND_ROW_START:],
        start_char=SECOND_ROW_START,
        prefix=TABLE_HEADER,
        prefix_start_char=HEADER_START,
    )
    assert chunk.text.count("| Rank | Reward |") == 2
    proposals = [
        {
            "name": "Rank",
            "kind": "ordered_scale",
            "evidence": "| Rank | Reward |",
            "members": [{"name": "A rank"}],
        }
    ]

    verified = verify_classes(
        proposals, document_text=document, source_id="ranks", chunk=chunk
    )

    span = verified[0].evidence
    assert span.start == HEADER_START
    assert span.start != second_header_start


def test_a_member_the_chunk_does_not_hold_is_rejected_even_though_the_document_does():
    """Membership is checked against the chunk, not the document. The model can
    only copy from what it was shown, so `S rank` -- present in this document,
    absent from this chunk -- is a name this call did not justify.

    Would pass with the check left against the whole document, which is why the
    fixture puts the name somewhere the document has it.
    """
    chunk = _rank_chunk()
    proposals = [
        {
            "name": "Rank",
            "kind": "ordered_scale",
            "evidence": "| Rank | Reward |",
            "members": [{"name": "A rank"}, {"name": "S rank"}],
        }
    ]

    verified = verify_classes(
        proposals, document_text=RANK_DOCUMENT, source_id="ranks", chunk=chunk
    )

    assert "S rank" in RANK_DOCUMENT
    assert [member.name for member in verified[0].members] == ["A rank"]
    assert [rejected.name for rejected in verified[0].rejected_members] == ["S rank"]


def _class(name: str, members, *, start: int = 0, declared: int | None = None):
    return DiscoveredClass(
        name=name,
        kind="unordered_set",
        evidence={"source_id": "doc", "start": start, "end": start + 5},
        members=[
            {"name": member} if isinstance(member, str) else member for member in members
        ],
        declared_count=declared,
    )


def test_a_member_two_chunks_both_found_appears_once():
    """The overlap between chunks guarantees this happens on any real document,
    and it is the property a reader notices first: a class listing `A rank`
    twice is visibly wrong. Fails on a merge that concatenates.
    """
    merged = merge_classes(
        [
            [_class("Rank", ["S rank", "A rank"])],
            [_class("Rank", ["A rank", "B rank"], start=400)],
        ]
    )

    assert len(merged) == 1
    assert [member.name for member in merged[0].members] == ["S rank", "A rank", "B rank"]


def test_a_merged_class_cites_the_first_chunk_that_stated_it():
    """The earliest occurrence is the one a reader wants to open; a later
    chunk's span points at the same header repeated further down."""
    merged = merge_classes(
        [
            [_class("Rank", ["S rank"], start=30)],
            [_class("Rank", ["A rank"], start=900)],
        ]
    )

    assert merged[0].evidence.start == 30


def test_a_count_stated_in_one_chunk_survives_the_chunks_that_did_not_state_it():
    """ "There are six difficulties" is one sentence in one chunk, and the
    other chunks holding members know nothing about it. Merging that keeps only
    the first chunk's `None` throws away the checksum the whole pass leans on
    for judging a short class."""
    merged = merge_classes(
        [
            [_class("Difficulty", ["EASY"])],
            [_class("Difficulty", ["APPEND"], start=400, declared=6)],
        ]
    )

    assert merged[0].declared_count == 6


def test_a_quoted_span_replaces_a_fallback_the_earlier_chunk_cited():
    """The one exception to "earliest chunk wins", and it only exists on a
    lenient pass. The first chunk kept a member occurrence because the quote
    was not in it; a later chunk of the same table held the header and located
    it. Both spans are real, and one names the class.

    Fails on a merge that takes `existing` unconditionally -- which is every
    other field's rule, and is why this needs its own test rather than riding
    on `test_a_merged_class_cites_the_first_chunk_that_stated_it`.
    """
    fallback = _class("Rank", ["S rank"], start=30).model_copy(
        update={"evidence_quoted": False}
    )
    merged = merge_classes([[fallback], [_class("Rank", ["A rank"], start=900)]])

    assert merged[0].evidence.start == 900
    assert merged[0].evidence_quoted is True


def test_a_fallback_does_not_displace_a_quote_an_earlier_chunk_located():
    """The other direction, which the same `if` decides and which a test on one
    arm alone would not pin: a lenient class arriving later must not overwrite
    a located quote with a member occurrence.
    """
    later = _class("Rank", ["A rank"], start=900).model_copy(update={"evidence_quoted": False})
    merged = merge_classes([[_class("Rank", ["S rank"], start=30)], [later]])

    assert merged[0].evidence.start == 30
    assert merged[0].evidence_quoted is True


def test_two_differently_named_classes_are_not_merged():
    """Merging is on the exact name. A guard against a merge keyed on anything
    looser -- the first member, the kind -- which would silently fold two real
    classes into one."""
    merged = merge_classes([[_class("Rank", ["S rank"])], [_class("Difficulty", ["EASY"])]])

    assert [found.name for found in merged] == ["Rank", "Difficulty"]


async def test_one_unreadable_chunk_does_not_discard_the_rest_of_the_document():
    """Counted and skipped, not fatal. A document at the ceiling is a dozen
    chunks and the sweep retries the *document*, so failing the whole document
    on one bad chunk makes a long document one that never completes.

    The cost is asserted rather than described: the class from the good chunk
    is recorded and nothing says a chunk was skipped.
    """
    recorder = _FakeRecorder()
    service = OntologyDiscoveryService(
        corpus=_FakeCorpus({"songs": SONGS}),
        model=_ScriptedModel(["I cannot do that", FOUND_ONE]),
        recorder=recorder,
        chunker=_FixedChunker(
            [
                DocumentChunk(text=SONGS, start_char=0),
                DocumentChunk(text=SONGS, start_char=0),
            ]
        ),
    )

    assert await service.discover("songs") == 1
    assert [found.name for found in recorder.recorded[0][2]] == ["Difficulty"]


async def test_a_document_whose_every_chunk_failed_is_not_recorded_at_all():
    """The transient shape -- an endpoint down, a model refusing everything.
    Recorded as "examined, no classes" it would retire every document in a
    project during one bad ten minutes, and nothing would ever retry them."""
    recorder = _FakeRecorder()
    service = OntologyDiscoveryService(
        corpus=_FakeCorpus({"songs": SONGS}),
        model=_ScriptedModel(["no", "still no"]),
        recorder=recorder,
        chunker=_FixedChunker(
            [
                DocumentChunk(text=SONGS, start_char=0),
                DocumentChunk(text=SONGS, start_char=0),
            ]
        ),
    )

    assert await service.discover("songs") is None
    assert recorder.recorded == []
