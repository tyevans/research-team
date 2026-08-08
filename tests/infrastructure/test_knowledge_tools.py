from uuid import uuid4

import pytest

from research_team.application.knowledge import (
    IngestReport,
    KnowledgeError,
    Match,
    MergeRecord,
)
from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools


class StubKnowledge:
    def __init__(self, *, report=None, matches=(), error=None):
        self._report = report
        self._matches = list(matches)
        self._error = error
        self.undone = []
        self.ingested = []

    async def ingest(self, source, *, report=None):
        if self._error:
            raise self._error
        self.ingested.append(source)
        return self._report

    async def search(self, query, *, limit=10):
        if self._error:
            raise self._error
        return self._matches[:limit]

    async def undo_merge(self, merge_id):
        if self._error:
            raise self._error
        self.undone.append(merge_id)
        return MergeRecord(
            merge_id=merge_id,
            canonical_name="Ada Lovelace",
            absorbed_names=("x",),
            reason="same",
        )


def tools_by_name(knowledge):
    return {tool.name: tool for tool in build_knowledge_tools(knowledge)}


@pytest.mark.asyncio
async def test_remember_reports_counts_and_confidence():
    report = IngestReport(
        source_id="notes",
        entity_count=7,
        relationship_count=4,
        domain="encyclopedia_wiki",
        domain_confidence=0.0,
    )
    tools = tools_by_name(StubKnowledge(report=report))

    result = await tools["remember"].ainvoke({"text": "t", "source_id": "notes"})

    assert "7" in result and "4" in result
    assert "encyclopedia_wiki" in result
    # A fallback must not read like a confident choice.
    assert "0.0" in result or "gave up" in result


@pytest.mark.asyncio
async def test_remember_lists_the_merges_so_the_agent_can_object():
    report = IngestReport(
        source_id="notes",
        entity_count=2,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
        merges=(
            MergeRecord(
                merge_id=uuid4(),
                canonical_name="Ada Lovelace",
                absorbed_names=("Lovelace, A.",),
                reason="same person",
            ),
        ),
    )
    tools = tools_by_name(StubKnowledge(report=report))

    result = await tools["remember"].ainvoke({"text": "t", "source_id": "notes"})

    assert "Ada Lovelace" in result
    assert str(report.merges[0].merge_id) in result


@pytest.mark.asyncio
async def test_a_failure_is_returned_as_text_not_raised():
    """The model cannot fix an outage; the person reading the log can."""
    tools = tools_by_name(StubKnowledge(error=KnowledgeError("endpoint down")))

    result = await tools["remember"].ainvoke({"text": "t", "source_id": "notes"})

    assert "endpoint down" in result


@pytest.mark.asyncio
async def test_graph_search_flattens_matches():
    matches = [
        Match(
            entity_id=uuid4(),
            name="Ada Lovelace",
            entity_type="Person",
            relationship_count=3,
        )
    ]
    tools = tools_by_name(StubKnowledge(matches=matches))

    result = await tools["graph_search"].ainvoke({"query": "ada"})

    assert "Ada Lovelace" in result and "Person" in result and "3" in result


@pytest.mark.asyncio
async def test_graph_search_says_so_when_empty():
    tools = tools_by_name(StubKnowledge(matches=[]))

    assert "No" in await tools["graph_search"].ainvoke({"query": "nothing"})


@pytest.mark.asyncio
async def test_unmerge_passes_the_id_through():
    knowledge = StubKnowledge()
    tools = tools_by_name(knowledge)
    merge_id = uuid4()

    result = await tools["unmerge"].ainvoke({"merge_id": str(merge_id)})

    assert knowledge.undone == [merge_id]
    assert "Ada Lovelace" in result


@pytest.mark.asyncio
async def test_unmerge_rejects_a_malformed_id_without_calling_the_port():
    knowledge = StubKnowledge()
    tools = tools_by_name(knowledge)

    result = await tools["unmerge"].ainvoke({"merge_id": "not-a-uuid"})

    assert knowledge.undone == []
    assert "not a valid merge id" in result


@pytest.mark.asyncio
async def test_remember_carries_the_provenance_fetch_returned():
    """`fetch` leads every page with `url:`, `title:` and `date:`. Those are
    the only record of where the text came from, and a corpus that drops them
    cannot recognise a page it already holds -- which is the whole reason
    `DocumentRecord.uri` exists.
    """
    report = IngestReport(
        source_id="s1",
        entity_count=1,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
    )
    knowledge = StubKnowledge(report=report)
    tools = tools_by_name(knowledge)

    await tools["remember"].ainvoke(
        {
            "text": "body",
            "source_id": "s1",
            "uri": "https://ex.example/a",
            "title": "A page",
            "published_at": "2026-01-02",
        }
    )

    (source,) = knowledge.ingested
    assert source.uri == "https://ex.example/a"
    assert source.title == "A page"
    assert source.published_at == "2026-01-02"


@pytest.mark.asyncio
async def test_remember_without_provenance_stores_none_not_empty_string():
    """Absent provenance and blank provenance must not be the same value. A
    corpus row holding `""` for its uri looks like a page fetched from
    nowhere; `None` says plainly that none was given.
    """
    report = IngestReport(
        source_id="s1",
        entity_count=1,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
    )
    knowledge = StubKnowledge(report=report)
    tools = tools_by_name(knowledge)

    await tools["remember"].ainvoke({"text": "body", "source_id": "s1"})

    (source,) = knowledge.ingested
    assert source.uri is None
    assert source.title is None
    assert source.published_at is None


@pytest.mark.asyncio
async def test_remember_passes_the_reporter_through_to_the_port():
    """The tool is the only caller of `ingest` in a real turn.

    A reporter that the composition root wires but the tool drops would leave
    the pane silent with nothing in the logs to say why.
    """
    seen = {}

    class RecordingKnowledge:
        async def ingest(self, source, *, report=None):
            seen["report"] = report
            return IngestReport(
                source_id=source.source_id,
                entity_count=0,
                relationship_count=0,
                domain=None,
                domain_confidence=None,
            )

    def reporter(note):
        pass

    tools = {
        tool.name: tool
        for tool in build_knowledge_tools(RecordingKnowledge(), report=reporter)
    }

    await tools["remember"].ainvoke({"text": "some text", "source_id": "notes"})

    assert seen["report"] is reporter
