from uuid import uuid4

import pytest

from research_team.application.knowledge import (
    IngestReport,
    KnowledgeError,
    Match,
    MergeRecord,
)
from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools
from research_team.infrastructure.agent.recall import PageMemo


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


def tools_by_name(knowledge, **kwargs):
    return {tool.name: tool for tool in build_knowledge_tools(knowledge, **kwargs)}


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


@pytest.mark.asyncio
async def test_remember_page_commits_what_fetch_retained():
    """The document is not passed. That is the point: a tool that required the
    model to re-emit twenty thousand characters got a summary instead, which
    ingests cleanly and quietly degrades the graph."""
    pages = PageMemo(stamp=lambda: "2026-08-10T12:00:00+00:00")
    pages.put(
        "https://example.com/a",
        text="the whole document",
        uri="https://example.com/a",
        title="A Paper",
        published_at="2026-01-02",
    )
    report = IngestReport(
        source_id="s1",
        entity_count=1,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
    )
    knowledge = StubKnowledge(report=report)
    tools = tools_by_name(knowledge, pages=pages)

    await tools["remember_page"].ainvoke({"url": "https://example.com/a", "source_id": "s1"})

    (source,) = knowledge.ingested
    assert source.text == "the whole document"
    assert source.uri == "https://example.com/a"
    assert source.title == "A Paper"
    assert source.published_at == "2026-01-02"
    assert source.fetched_at == "2026-08-10T12:00:00+00:00"
    assert source.source_id == "s1"


@pytest.mark.asyncio
async def test_remember_page_carries_the_note_the_agent_wrote():
    """The note is the model's actual contribution and the one argument it is
    right to ask for."""
    pages = PageMemo(stamp=lambda: "t")
    pages.put("https://example.com/a", text="body", uri="https://example.com/a")
    report = IngestReport(
        source_id="s1",
        entity_count=0,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
    )
    knowledge = StubKnowledge(report=report)
    tools = tools_by_name(knowledge, pages=pages)

    await tools["remember_page"].ainvoke(
        {"url": "https://example.com/a", "source_id": "s1", "note": "why it matters"}
    )

    (source,) = knowledge.ingested
    assert source.note == "why it matters"


@pytest.mark.asyncio
async def test_an_unretained_page_names_the_url_and_stores_nothing():
    """Degrades in band rather than silently. A `remember_page` that quietly
    stored nothing would be indistinguishable from one that worked, and the
    corpus would be missing a document nobody was told about."""
    knowledge = StubKnowledge()
    tools = tools_by_name(knowledge, pages=PageMemo())

    result = await tools["remember_page"].ainvoke(
        {"url": "https://example.com/gone", "source_id": "s1"}
    )

    assert knowledge.ingested == []
    assert "https://example.com/gone" in result
    assert "fetch" in result


@pytest.mark.asyncio
async def test_remember_page_reports_what_it_recorded():
    """The same report `remember` returns, from the same formatter -- two
    renderings of one ingest would eventually disagree."""
    pages = PageMemo(stamp=lambda: "t")
    pages.put("https://example.com/a", text="body", uri="https://example.com/a")
    report = IngestReport(
        source_id="s1",
        entity_count=0,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
    )
    tools = tools_by_name(StubKnowledge(report=report), pages=pages)

    result = await tools["remember_page"].ainvoke(
        {"url": "https://example.com/a", "source_id": "s1"}
    )

    assert "Recorded s1" in result


@pytest.mark.asyncio
async def test_a_page_ingest_failure_is_returned_as_text_not_raised():
    """As `remember` does: a tool that raises turns an outage into a broken
    turn."""
    pages = PageMemo(stamp=lambda: "t")
    pages.put("https://example.com/a", text="body", uri="https://example.com/a")
    tools = tools_by_name(StubKnowledge(error=KnowledgeError("endpoint down")), pages=pages)

    result = await tools["remember_page"].ainvoke(
        {"url": "https://example.com/a", "source_id": "s1"}
    )

    assert "Could not record this" in result


def test_remember_page_is_absent_without_a_page_memo():
    """A tool that could never resolve anything is worse than an absent one:
    the model would spend turns on it and be told to fetch a page it had just
    fetched."""
    tools = tools_by_name(StubKnowledge())

    assert "remember_page" not in tools
    assert "remember" in tools


def test_remember_page_is_gated():
    """A commit is a commit however the bytes arrived. An ungated by-reference
    path would be a way around the gate on the by-value one."""
    from research_team.application.autonomy import GATED_TOOLS, REMEMBER_PAGE_TOOL

    assert REMEMBER_PAGE_TOOL in GATED_TOOLS
