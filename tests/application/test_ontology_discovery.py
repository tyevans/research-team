"""Discovery's pure half: what the model is asked, and what is believed back."""

from research_team.application.corpus_read import StoredDocument
from research_team.application.ontology_discovery import (
    MAX_DISCOVERY_CHARS,
    OntologyDiscoveryService,
    build_prompt,
    parse_ontology,
    verify_classes,
)
from research_team.domain.corpus import TextRecord

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
    )

    assert await service.discover("exact") == 0
    assert len(model.prompts) == 1


async def test_an_unknown_source_is_none_rather_than_an_exception():
    """A caller guessing at a source id is the ordinary case, the same
    reasoning `CorpusReadPort.read_document` gives for its own `None`."""
    service, _ = _service()

    assert await service.discover("nope") is None


async def test_the_whole_document_reaches_the_prompt():
    """Never chunks. The rank table's class name lives entirely in its
    one-line header, and a pass that saw only part of a document could be
    blind to exactly the case this feature exists for."""
    model = _FakeModel('{"classes": []}')
    service = OntologyDiscoveryService(
        corpus=_FakeCorpus({"songs": SONGS}), model=model, recorder=_FakeRecorder()
    )

    await service.discover("songs")

    assert SONGS in model.prompts[0]
