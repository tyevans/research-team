"""Ontology discovery service orchestration tests."""

from research_team.knowledge.application.ontology_discovery import (
    MAX_DISCOVERY_CHARS,
    DocumentChunk,
    OntologyDiscoveryService,
)
from research_team.research.application.corpus_read import StoredDocument
from research_team.research.domain.corpus import TextRecord

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
        '"evidence": "There are seven difficulties", "members": [{"name": "EASY"}]}]}'
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
