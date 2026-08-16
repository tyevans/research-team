"""A stored video reaching the knowledge graph through its transcript.

The whole point of the perception slice, and until this file nothing asserted
it end to end. Every other test of the feature holds one seam still: the
domain suite folds events, the read-model suite drives the projection, the
route suite stops at the derived row. Each of those can be green while the
chain they belong to is broken in a joint none of them looks at -- which is
how a build with no `EntityDefinitionRunner` in `composition.py` once served
every definition request as an empty cache miss with a full suite passing.

Built over a composed application (`build_application`), so the wiring under
test is the one that ships. Two things are faked and both are stated rather
than implied:

- The `PerceptionPort`, injected through `build_application(perception=...)`,
  which is that parameter's whole reason for existing. **Nothing here reaches
  a network or names a model host.** The adapter that speaks to one is tested
  in `tests/infrastructure/test_readeverything_adapter.py`.
- The chat model, a `FakeMessagesListChatModel` answering with a fixed
  extraction. It is also the extraction model (`_extraction_model` hands an
  injected model straight back), so what runs is redstring's real
  `build_graph` over a provider that does not think -- and, because it is the
  same instance, it is where the transcript can be *seen* arriving. See
  `PromptRecordingModel`.

`AGENT_VECTOR_STORE=none` for the same no-network reason: the default builds
an embedding provider that reaches `AGENT_EMBEDDING_BASE_URL` on first ingest,
and without this the test hangs against whatever that happens to be. Measured
-- it is how the first draft of this file behaved. A local workaround, not a
fix; `BACKLOG.md` B89 is the repository-wide one.
"""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.application.perception import (
    LocatorSpan,
    Perceived,
    PerceptionCapabilities,
)
from research_team.composition import build_application
from research_team.interfaces.web.app import create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue

pytestmark = pytest.mark.asyncio

#: What the fake transcriber says the video says. Nothing else in the project
#: says anything, which is what makes the graph below traceable to it: the
#: derived source is the only thing extracted, so an entity in the graph came
#: from this sentence or from nowhere.
TRANSCRIPT = "Ada Lovelace worked with Charles Babbage on the Analytical Engine."

#: redstring's extraction shape, answered by the fake model to every call.
#: The names are the transcript's, which reads well and proves nothing on its
#: own -- see `TRANSCRIPT` for where the traceability actually comes from.
EXTRACTION = json.dumps(
    {
        "entities": [
            {"name": "Ada Lovelace", "entity_type": "Person"},
            {"name": "Analytical Engine", "entity_type": "Machine"},
        ],
        "relationships": [
            {
                "source_name": "Ada Lovelace",
                "target_name": "Analytical Engine",
                "relationship_type": "WORKED_ON",
            }
        ],
    }
)


class FakeTranscriber:
    """A `PerceptionPort` that transcribes without a transcriber.

    Counts its calls, because "the port was reached" and "a row appeared" are
    different claims and a cached or fabricated row would satisfy the second
    without the first.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        self.calls.append(sha256)
        return Perceived(
            text=TRANSCRIPT,
            locators=(
                LocatorSpan(
                    0, len(TRANSCRIPT), {"kind": "time", "start_s": 0.0, "end_s": 9.0}
                ),
            ),
            fingerprint="asr=whisper-1",
            degradations=(),
        )

    def capabilities(self) -> PerceptionCapabilities:
        return PerceptionCapabilities(vision=True, asr=True, ffmpeg=True)


class PromptRecordingModel(FakeMessagesListChatModel):
    """The library's fake, plus a record of every prompt it was shown.

    This is what turns the graph assertion below from an elimination argument
    into a data-flow one. The model answers the same extraction whatever it is
    given, so the entity names prove nothing on their own -- but the *prompt*
    is the one place the perceived text has to appear if it genuinely travelled
    from the blob, through the port, into `corpus_documents`, out through
    `DocumentExtractor` and into redstring's chunker. Recording it is cheaper
    than a provider fake and needs no injection point `build_application` does
    not already have: `_extraction_model` hands an injected model straight
    back, so this instance *is* the extraction model.

    A pydantic field rather than a plain attribute, because `BaseChatModel` is
    a pydantic model and an ordinary `self.seen = []` in `__init__` would be
    rejected. Pydantic gives each instance its own list, so the mutable default
    is safe here in a way it would not be on a dataclass.

    `bind_tools` is not overridden the way `ToolAwareFakeChatModel` does it:
    nothing in this file runs an agent turn, and extraction binds no tools.
    """

    seen: list[str] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append("\n".join(str(message.content) for message in messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.fixture
async def wired(db_path, monkeypatch):
    """A composed application, its HTTP surface, and the queue both share."""
    monkeypatch.setenv("AGENT_VECTOR_STORE", "none")
    port = FakeTranscriber()
    model = PromptRecordingModel(responses=[AIMessage(content=EXTRACTION)])
    application = build_application(
        model=model,
        db_path=db_path,
        perception=port,
    )
    await application.start()
    queue = ExtractionQueue()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        editor=application.editor,
        extraction=ExtractionActivity(),
        extract_queue=queue,
        extractor=application.document_extractor,
        graphs=application.graphs,
        perception=application.perception,
        perceiver=application.perceiver,
    )
    client = AsyncClient(transport=ASGITransport(app=api), base_url="http://test")
    async with client:
        yield application, client, queue, port, model
    await application.close()


async def _rows(client: AsyncClient, project: str) -> dict[str, dict]:
    listed = await client.get(f"/api/projects/{project}/sources")
    assert listed.status_code == 200
    return {row["source_id"]: row for row in listed.json()}


async def test_a_stored_video_reaches_the_graph_through_its_transcript(wired):
    """The whole point of the slice, and nothing else asserts it end to end.

    Store media -> perceive -> the derived source appears in `unextracted` ->
    extract -> the graph holds an entity from what was said.

    **Why the entity is traceable to the transcript rather than to the fake.**
    The model answers the same extraction whatever it is shown, so the entity
    *names* prove nothing. The prompt does: `PromptRecordingModel` keeps every
    prompt it was handed, and the transcript has to appear in one of them, in
    full. That is data flow rather than inference -- the sentence the fake port
    invented for a twelve-byte blob turns up in the text the extraction model
    was asked about, so it travelled blob -> port -> `corpus_documents` ->
    `DocumentExtractor` -> redstring's chunker without anything in between
    substituting for it.

    Two weaker claims are kept alongside it, because they fail differently: the
    graph is asserted empty before extraction (so a stale graph cannot supply
    the entity), and the 202 names exactly one source id (so the medium was not
    extracted as if it were prose).

    **What is deliberately not asserted: `extracted` flipping to true.** It
    does not, within ten seconds, and it does not for an ordinary fetched
    document either -- measured on 2026-08-16 by adding a plain text source to
    this same flow and extracting both. The `DocumentExtracted` handler that
    would set `extracted_at` (`CorpusProjection._on_extracted`) never sees the
    event under `AGENT_GRAPH_STORE=memory`, and `corpus_caught_up()` times out
    on the same position. That is a pre-existing gap this slice neither caused
    nor is in a position to fix; asserting it here would make this file red
    about somebody else's bug and hide the one it is for. Filed as `BACKLOG.md`
    B88, with the measurement, rather than left as a note in one docstring.
    """
    application, client, queue, port, model = wired
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    assert created.status_code == 200
    project = created.json()["id"]
    project_id = UUID(project)

    stored = await client.post(
        f"/api/projects/{project}/sources/media",
        files={"file": ("talk.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
        data={"source_id": "vid"},
    )
    assert stored.status_code == 201
    empty = await client.get(f"/api/projects/{project}/graph/entities")
    assert empty.json()["entities"] == [], "the graph must start with nothing in it"

    perceived = await client.post(f"/api/projects/{project}/sources/vid/perceive")
    assert perceived.status_code == 202
    await queue.wait(project_id)
    await application.corpus_caught_up()

    assert port.calls, "the port was never asked to read the blob"
    rows = await _rows(client, project)
    assert rows["vid#perceived"]["kind"] == "text"
    assert rows["vid#perceived"]["derived_from"] == "vid"
    # An empty list, not the `<degradations could not be read>` marker: this
    # perception missed nothing, and saying otherwise on the ordinary path was
    # a real defect this test found (`_degradations_of`, `read_models.py`).
    assert rows["vid#perceived"]["degradations"] == []
    row = await application.corpus.get(project_id, "vid#perceived")
    assert row is not None
    assert row.text == TRANSCRIPT
    assert row.perceived_with == "asr=whisper-1"
    assert json.loads(row.locator_map) == [
        {
            "char_start": 0,
            "char_end": len(TRANSCRIPT),
            "locator": {"kind": "time", "start_s": 0.0, "end_s": 9.0},
        }
    ]

    # The derived source queues for extraction on its own, and the medium does
    # not: one source id, and it is the transcript's.
    assert await application.document_extractor.unextracted(project_id) == ("vid#perceived",)

    queued = await client.post(f"/api/projects/{project}/sources/extract")
    assert queued.status_code == 202
    assert queued.json()["source_ids"] == ["vid#perceived"]
    await queue.wait(project_id)

    outcome = next(
        finished
        for finished in queue.finished(project_id)
        if finished["source_id"] == "vid#perceived"
    )
    assert outcome["status"] == "done", outcome
    assert outcome["entities"] >= 1

    # The data-flow half. Nothing before this line shows the *transcript*
    # reaching the extraction -- only that an extraction happened for a source
    # id whose row holds the transcript.
    assert any(TRANSCRIPT in prompt for prompt in model.seen), model.seen

    listed = await client.get(f"/api/projects/{project}/graph/entities")
    assert listed.status_code == 200
    names = {entity["name"] for entity in listed.json()["entities"]}
    assert "Ada Lovelace" in names, listed.json()


async def test_the_medium_itself_never_reaches_the_graph(wired):
    """A video is not a document, and the queue must not treat it as one.

    The failure this rules out is the one `DocumentExtractor.unextracted`'s
    docstring warns about: teach the filter about media and a video and its
    transcript become two queue entries for one extraction, the second of
    which extracts a blob as if it were prose. Before perception there is
    nothing extractable in this project at all, and the 202 has to say so.

    Would pass with the whole perception slice reverted, which is the point --
    it is the invariant the slice had to preserve, not something it added.
    """
    _application, client, _queue, _port, _model = wired
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    project = created.json()["id"]
    stored = await client.post(
        f"/api/projects/{project}/sources/media",
        files={"file": ("talk.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
        data={"source_id": "vid"},
    )
    assert stored.status_code == 201

    queued = await client.post(f"/api/projects/{project}/sources/extract")

    assert queued.status_code == 202
    assert queued.json() == {"queued": 0, "source_ids": []}
    await asyncio.sleep(0)
    assert (await client.get(f"/api/projects/{project}/graph/entities")).json()[
        "entities"
    ] == []


async def _row_when(application, project_id: UUID, source_id: str, ready, *, timeout=10.0):
    """The transcript's row once `ready(row)` holds, or a failure saying it never did.

    A poll rather than `application.corpus_caught_up()`, and the reason is
    B88 rather than flakiness. `CorpusEditor._store_derived` re-indexes after
    it stores -- it has to, or the chunk store goes on quoting text the
    corpus no longer holds -- and indexing appends redstring events that the
    corpus subscription never processes, so `caught_up` waits for a position
    it will not reach and times out after ten seconds. Measured on 2026-08-16
    by deleting the `index` call: the identical assertions pass in 0.8s.

    The corpus event is appended *before* those, so the row does arrive; what
    is unavailable is the "everything has landed" signal. Polling for the
    value under test is the honest substitute -- it waits for the fact the
    test is about rather than for a global barrier that answers a different
    question.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    row = None
    while asyncio.get_running_loop().time() < deadline:
        row = await application.corpus.get(project_id, source_id, include_dropped=True)
        if row is not None and ready(row):
            return row
        await asyncio.sleep(0.01)
    raise AssertionError(f"{source_id!r} never reached the expected state; last row: {row}")


async def _perceived_video(client, queue, application) -> str:
    """A project holding `vid` and its transcript `vid#perceived`.

    Goes through the HTTP surface rather than seeding rows, for this file's
    reason and one more: the defect these tests cover was in `CorpusEditor`,
    which only the routes reach, and a fixture that executed `StoreDerivedText`
    itself would prove the aggregate accepts a re-store while leaving the
    editor -- the thing that was broken -- untouched.
    """
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    assert created.status_code == 200
    project = created.json()["id"]
    stored = await client.post(
        f"/api/projects/{project}/sources/media",
        files={"file": ("talk.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
        data={"source_id": "vid"},
    )
    assert stored.status_code == 201
    perceived = await client.post(f"/api/projects/{project}/sources/vid/perceive")
    assert perceived.status_code == 202
    await queue.wait(UUID(project))
    await application.corpus_caught_up()
    return project


async def test_a_dropped_transcript_can_be_restored(wired):
    """Restore works on a transcript, and keeps everything perception recorded.

    The blocking defect of the whole-branch review. `CorpusEditor.restore`
    resolved the transcript through `read_document` -- correct, it *is* a text
    row -- and then re-stored it with `StoreSourceDocument`, which the
    derivedness guard refuses. The console offers Restore on every dropped
    text row, so pressing it answered with a refusal saying the operator had
    tried to overwrite a transcript with prose nobody perceived, and the only
    way back was to pay for the model call again.

    Proved red against the code before the fix: `RESTORE REFUSED: source
    'vid#perceived' is derived from 'vid'` arrived as a 500, since nothing at
    the route maps `CommandRejectedError` on that path.

    The provenance assertions are the second half and are not decoration. A
    restore that re-issued `StoreDerivedText` with the perception fields left
    at their defaults would put the row back and silently erase what produced
    it -- the same failure `fetched_at` is carried through to avoid, one field
    class over. `locator_map` in particular could not be asserted at all until
    it had a reader, which is why F2 had to land with this.
    """
    application, client, queue, _port, _model = wired
    project = await _perceived_video(client, queue, application)
    project_id = UUID(project)

    before = await application.corpus.get(project_id, "vid#perceived")
    assert before is not None

    dropped = await client.post(
        f"/api/projects/{project}/sources/vid%23perceived/drop",
        json={"reason": "noisy"},
    )
    assert dropped.status_code == 200, dropped.text
    await application.corpus_caught_up()
    # Read off the row rather than the listing: `_rows` uses the default
    # `list_sources`, which hides dropped rows, so the transcript is
    # legitimately absent from it at this point.
    gone = await application.corpus.get(project_id, "vid#perceived", include_dropped=True)
    assert gone is not None and gone.dropped_reason == "noisy"
    assert "vid#perceived" not in await _rows(client, project)

    restored = await client.post(f"/api/projects/{project}/sources/vid%23perceived/restore")
    assert restored.status_code == 200, restored.text

    row = await _row_when(
        application, project_id, "vid#perceived", lambda r: r.dropped_reason is None
    )
    assert row.dropped_reason is None
    assert row.text == TRANSCRIPT
    assert row.derived_from == "vid"
    assert row.perceived_with == before.perceived_with
    assert row.locator_map == before.locator_map
    assert row.degradations == before.degradations


async def test_a_transcripts_title_can_be_revised_and_its_text_cannot(wired):
    """The other half of the same defect, and the line the fix must not cross.

    Revising took the identical `StoreSourceDocument` path, so a transcript's
    title could not be corrected at all. It must work -- a title is an
    ordinary edit whatever produced the text under it.

    The `text` refusal is the opposite requirement and needs its own
    assertion, because unlike media it cannot be left to the aggregate:
    `StoreDerivedText` with a changed `text` is exactly the shape a legitimate
    re-perception has, so `decide` sees nothing wrong and would store a
    hand-typed paragraph as something a model perceived. 400 with a message
    naming re-perception, not a silently dropped field.

    Proved red both ways: the title half answered 500 before the fix, and the
    text half answered 200 with the transcript replaced when the refusal was
    removed.
    """
    application, client, queue, _port, _model = wired
    project = await _perceived_video(client, queue, application)
    project_id = UUID(project)
    original = await application.corpus.get(project_id, "vid#perceived")
    assert original is not None
    before_title = original.title

    renamed = await client.patch(
        f"/api/projects/{project}/sources/vid%23perceived",
        json={"title": "Ada's talk, transcribed", "note": "check the last minute"},
    )
    assert renamed.status_code == 200, renamed.text

    row = await _row_when(
        application, project_id, "vid#perceived", lambda r: r.title != before_title
    )
    assert row.title == "Ada's talk, transcribed"
    assert row.note == "check the last minute"
    # The edit changed metadata and nothing else: the transcript and every
    # field recording how it was produced survive a title fix.
    assert row.text == TRANSCRIPT
    assert row.derived_from == "vid"
    assert row.perceived_with == "asr=whisper-1"

    edited = await client.patch(
        f"/api/projects/{project}/sources/vid%23perceived",
        json={"text": "something nobody said"},
    )
    assert edited.status_code == 400, edited.text
    assert "perceive the medium again" in edited.json()["detail"]

    # `uri` and `published_at` go the same way and for a related reason: a
    # transcript was not fetched from anywhere, so `CorpusDerivedTextStored`
    # has no field to put them in. Refused rather than dropped, because
    # answering 200 over a field that went nowhere is the worst of the three
    # available answers.
    relocated = await client.patch(
        f"/api/projects/{project}/sources/vid%23perceived",
        json={"uri": "https://example.invalid/talk"},
    )
    assert relocated.status_code == 400, relocated.text
    assert "no uri or publication date" in relocated.json()["detail"]

    # No poll: a refused edit appends nothing, so there is no later state to
    # wait for. Reading immediately is what makes this assertion meaningful --
    # it is asserting that nothing happened, not that something did.
    unchanged = await application.corpus.get(project_id, "vid#perceived")
    assert unchanged is not None
    assert unchanged.text == TRANSCRIPT
