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
  `build_graph` over a provider that does not think.

`AGENT_VECTOR_STORE=none` for the same no-network reason: the default builds
an embedding provider that reaches `AGENT_EMBEDDING_BASE_URL` on first ingest,
and without this the test hangs against whatever that happens to be. Measured
-- it is how the first draft of this file behaved.
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


@pytest.fixture
async def wired(db_path, monkeypatch):
    """A composed application, its HTTP surface, and the queue both share."""
    monkeypatch.setenv("AGENT_VECTOR_STORE", "none")
    port = FakeTranscriber()
    application = build_application(
        model=FakeMessagesListChatModel(responses=[AIMessage(content=EXTRACTION)]),
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
        yield application, client, queue, port
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
    *names* prove nothing. What proves it is the corpus: the project holds one
    medium and one derived source, the medium is never extracted (media are
    filtered out of `unextracted`, and the 202 below names exactly one source
    id), and the graph is asserted empty before the extraction runs. An entity
    afterwards therefore came from the perceived text, by elimination.

    **What is deliberately not asserted: `extracted` flipping to true.** It
    does not, within ten seconds, and it does not for an ordinary fetched
    document either -- measured on 2026-08-16 by adding a plain text source to
    this same flow and extracting both. The `DocumentExtracted` handler that
    would set `extracted_at` (`CorpusProjection._on_extracted`) never sees the
    event under `AGENT_GRAPH_STORE=memory`, and `corpus_caught_up()` times out
    on the same position. That is a pre-existing gap this slice neither caused
    nor is in a position to fix; asserting it here would make this file red
    about somebody else's bug and hide the one it is for. Reported alongside
    the task rather than left silent.
    """
    application, client, queue, port = wired
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
    _application, client, _queue, _port = wired
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
