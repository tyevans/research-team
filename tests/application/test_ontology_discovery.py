"""Discovery's pure half: what the model is asked, and what is believed back."""

from research_team.application.corpus_read import StoredDocument
from research_team.application.ontology_discovery import (
    MAX_DISCOVERY_CHARS,
    DocumentChunk,
    OntologyDiscoveryService,
    build_prompt,
    merge_classes,
    parse_ontology,
    verify_classes,
)
from research_team.domain.corpus import TextRecord
from research_team.domain.ontology import DiscoveredClass

SONGS = (
    "There are six difficulties available in the game: EASY, NORMAL, HARD, "
    "EXPERT, MASTER, and APPEND. Achieving combo milestones grants coins."
)


def test_the_prompt_carries_the_document_and_forbids_outside_knowledge():
    prompt = build_prompt(SONGS)

    assert SONGS in prompt
    assert "outside the document" in prompt


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
            "evidence": {"start": 0, "end": 100},
            "members": [{"name": "EASY", "ordinal": 0}, {"name": "LEGEND", "ordinal": 6}],
        }
    ]

    (klass,) = verify_classes(proposals, document_text=SONGS, source_id="songs")

    assert [member.name for member in klass.members] == ["EASY"]
    assert klass.rejected_members[0].name == "LEGEND"
    assert "not found" in klass.rejected_members[0].reason


def test_a_class_whose_evidence_span_is_outside_the_document_is_dropped_whole():
    """An evidence span that does not exist is a span the model produced rather
    than read, and a class nobody can open the source for is exactly the
    unjudgeable artefact this feature exists to avoid. Dropping the class is
    right where dropping a member is not: without evidence there is nothing
    left to judge, so recording it would record something uncheckable."""
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": {"start": 9000, "end": 9100},
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
            "evidence": {"start": 0, "end": 50},
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
            "evidence": {"start": 0, "end": 50},
            "members": [{"name": "EASY"}],
        }
    ]

    assert verify_classes(proposals, document_text=SONGS, source_id="songs") == []


def test_the_evidence_span_is_carried_with_the_source_it_came_from():
    """The span is what makes a class judgeable: the view opens the source
    document at these offsets. A class carrying members and no usable span
    renders as an assertion with no way to check it."""
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": {"start": 0, "end": 66},
            "members": [{"name": "EASY", "ordinal": 0}],
        }
    ]

    (klass,) = verify_classes(proposals, document_text=SONGS, source_id="songs")

    assert klass.evidence.source_id == "songs"
    assert SONGS[klass.evidence.start : klass.evidence.end].startswith("There are six")


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
            "evidence": {"start": 0, "end": 66},
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


# --- the service -------------------------------------------------------------

FOUND_ONE = (
    '{"classes": [{"name": "Difficulty", "kind": "ordered_scale", '
    '"declared_count": 6, "evidence": {"start": 0, "end": 66}, '
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


class _FakeModel:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class _WholeDocumentChunker:
    """`DocumentChunkPort` that does not cut: one chunk, no prefix, offset 0.

    The identity case, so the tests that predate chunking keep asserting what
    they always asserted -- verification, refusal, recording -- without the
    chunking arithmetic in the way. The chunking behaviour has its own fakes
    below.
    """

    def chunk(self, text):
        return [DocumentChunk(text=text, start_char=0)]


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


def _service(*, documents=None, reply=FOUND_ONE, recorder=None):
    return (
        OntologyDiscoveryService(
            corpus=_FakeCorpus(documents if documents is not None else {"songs": SONGS}),
            model=_FakeModel(reply),
            recorder=recorder if recorder is not None else _FakeRecorder(),
            chunker=_WholeDocumentChunker(),
        ),
        recorder,
    )


async def test_discovery_records_the_classes_the_document_supports():
    recorder = _FakeRecorder()
    service, _ = _service(recorder=recorder)

    assert await service.discover("songs") == 1

    source_id, model_version, classes = recorder.recorded[0]
    assert (source_id, model_version) == ("songs", "fake-model")
    assert classes[0].members[0].name == "EASY"


async def test_a_document_that_states_no_classes_is_still_recorded():
    """An empty result is a real outcome and has to reach the recorder, or the
    ungrouped sweep re-runs this document on every pass forever, at model cost.
    Would pass with an early return on an empty list if this only asserted the
    return value, which is why it asserts the call happened."""
    recorder = _FakeRecorder()
    service, _ = _service(reply='{"classes": []}', recorder=recorder)

    assert await service.discover("songs") == 0
    assert len(recorder.recorded) == 1
    assert recorder.recorded[0][2] == []


async def test_an_unreadable_reply_records_nothing_at_all():
    """Distinct from the empty case above, and the distinction is the point.
    An empty answer is the model saying "no classes here"; an unreadable one is
    the model saying nothing anyone can read, and recording that as "examined,
    none found" would mark the document done and stop anyone retrying it."""
    recorder = _FakeRecorder()
    service, _ = _service(reply="sorry, I cannot", recorder=recorder)

    assert await service.discover("songs") is None
    assert recorder.recorded == []


async def test_a_reply_whose_classes_all_fail_verification_is_recorded_as_empty():
    """Third case, between the two above. The reply parsed, so the model was
    understood; nothing it proposed survived the document. That is "examined,
    states none" -- the document is done, and re-running it would produce the
    same refusal at the same cost."""
    recorder = _FakeRecorder()
    invented = (
        '{"classes": [{"name": "Difficulty", "kind": "ordered_scale", '
        '"evidence": {"start": 9000, "end": 9100}, "members": [{"name": "EASY"}]}]}'
    )
    service, _ = _service(reply=invented, recorder=recorder)

    assert await service.discover("songs") == 0
    assert recorder.recorded[0][2] == []


async def test_a_document_over_the_ceiling_is_refused_before_the_model_is_called():
    """Refused, not truncated: a truncated read drops a document's second half
    silently and reports success. The model must not be called at all, or the
    refusal costs the same as the work it declined to do."""
    model = _FakeModel(FOUND_ONE)
    recorder = _FakeRecorder()
    service = OntologyDiscoveryService(
        corpus=_FakeCorpus({"huge": "x" * (MAX_DISCOVERY_CHARS + 1)}),
        model=model,
        recorder=recorder,
        chunker=_WholeDocumentChunker(),
    )

    assert await service.discover("huge") is None
    assert model.prompts == []
    # Not recorded as examined either -- it stays on the sweep, so raising the
    # ceiling or building the windowed pass later picks it up.
    assert recorder.recorded == []


async def test_a_document_exactly_at_the_ceiling_is_read():
    """The boundary is inclusive. An off-by-one here silently refuses a
    document that fits, and the refusal looks identical to a document that
    does not."""
    model = _FakeModel('{"classes": []}')
    service = OntologyDiscoveryService(
        corpus=_FakeCorpus({"exact": "x" * MAX_DISCOVERY_CHARS}),
        model=model,
        recorder=_FakeRecorder(),
        chunker=_WholeDocumentChunker(),
    )

    assert await service.discover("exact") == 0
    assert len(model.prompts) == 1


async def test_an_unknown_source_is_none_rather_than_an_exception():
    """A caller guessing at a source id is the ordinary case, the same
    reasoning `CorpusReadPort.read_document` gives for its own `None`."""
    service, _ = _service()

    assert await service.discover("nope") is None


async def test_every_chunk_the_chunker_produced_reaches_the_prompt():
    """A pass that chunks and then reads only the first chunk is the silent
    version of the bug this change fixes -- it succeeds, records classes, and
    is blind to the other 90% of the article. Fails with a `break` after the
    first chunk, which is exactly what a partial implementation looks like."""
    model = _ScriptedModel(['{"classes": []}'] * 3)
    service = OntologyDiscoveryService(
        corpus=_FakeCorpus({"songs": SONGS}),
        model=model,
        recorder=_FakeRecorder(),
        chunker=_FixedChunker(
            [
                DocumentChunk(text="first", start_char=0),
                DocumentChunk(text="second", start_char=5),
                DocumentChunk(text="third", start_char=11),
            ]
        ),
    )

    await service.discover("songs")

    assert len(model.prompts) == 3
    assert [("first" in model.prompts[0]), ("second" in model.prompts[1])] == [True, True]
    assert "third" in model.prompts[2]


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

    The span given is offsets 26..36 of the *chunk*, which is `| A rank |`
    inside it. Untranslated, offsets 26..36 of the document land in the header
    line -- a real range, inside the document, that renders perfectly and
    quotes the wrong text. Fails with the translation removed.
    """
    chunk = _rank_chunk()
    row_in_chunk = chunk.text.index("| A rank |")
    proposals = [
        {
            "name": "Rank",
            "kind": "ordered_scale",
            "evidence": {"start": row_in_chunk, "end": row_in_chunk + 10},
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
            "evidence": {"start": 0, "end": 17},
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
            "evidence": {"start": 0, "end": len(TABLE_HEADER) + 10},
            "members": [{"name": "A rank"}],
        }
    ]

    verified = verify_classes(
        proposals, document_text=RANK_DOCUMENT, source_id="ranks", chunk=chunk
    )

    span = verified[0].evidence
    assert (span.start, span.end) == (HEADER_START, ROWS_START)
    assert "S rank" not in RANK_DOCUMENT[span.start : span.end]


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
            "evidence": {"start": 0, "end": 17},
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
