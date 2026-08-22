from uuid import uuid4

import pytest

from research_team.application.knowledge import (
    IngestReport,
    KnowledgeError,
    Match,
    MergeRecord,
    SearchMode,
    SearchOutcome,
    source_id_for_url,
)
from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools
from research_team.infrastructure.agent.recall import PageMemo


class StubKnowledge:
    def __init__(
        self,
        *,
        report=None,
        matches=(),
        error=None,
        search_mode=SearchMode.FUSED,
        described=(),
        describe_mode=SearchMode.CARDS,
    ):
        self._report = report
        self._matches = list(matches)
        self._error = error
        self._search_mode = search_mode
        self._described = list(described)
        self._describe_mode = describe_mode
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
        return SearchOutcome(matches=tuple(self._matches[:limit]), mode=self._search_mode)

    async def describe(self, query, *, limit=10):
        if self._error:
            raise self._error
        return SearchOutcome(matches=tuple(self._described[:limit]), mode=self._describe_mode)

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
    `TextRecord.uri` exists.
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

    await tools["remember_page"].ainvoke({"url": "https://example.com/a"})

    (source,) = knowledge.ingested
    assert source.text == "the whole document"
    assert source.uri == "https://example.com/a"
    assert source.title == "A Paper"
    assert source.published_at == "2026-01-02"
    assert source.fetched_at == "2026-08-10T12:00:00+00:00"
    # Derived from the url rather than supplied: this used to be `"s1"`, passed
    # as a `source_id` argument the tool no longer takes. Asserted against
    # `source_id_for_url` rather than the literal so this test says *which*
    # rule it is pinning -- a literal would also pass if the tool started
    # deriving the id some other way that happened to agree on this one url.
    assert source.source_id == source_id_for_url("https://example.com/a")


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
        {"url": "https://example.com/a", "note": "why it matters"}
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

    result = await tools["remember_page"].ainvoke({"url": "https://example.com/gone"})

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

    result = await tools["remember_page"].ainvoke({"url": "https://example.com/a"})

    assert "Recorded s1" in result


@pytest.mark.asyncio
async def test_a_page_ingest_failure_is_returned_as_text_not_raised():
    """As `remember` does: a tool that raises turns an outage into a broken
    turn."""
    pages = PageMemo(stamp=lambda: "t")
    pages.put("https://example.com/a", text="body", uri="https://example.com/a")
    tools = tools_by_name(StubKnowledge(error=KnowledgeError("endpoint down")), pages=pages)

    result = await tools["remember_page"].ainvoke({"url": "https://example.com/a"})

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


def test_knowledge_prompt_keeps_committing_is_not_free():
    """This sentence is what makes committing a decision rather than a
    reflex, and it applies to both the by-value `remember` path and the
    by-reference `remember_page` path -- nothing about adding the second path
    should ever cost the model this warning on the first."""
    from research_team.infrastructure.agent.knowledge_tools import KNOWLEDGE_PROMPT

    assert "Committing is not free and not private" in KNOWLEDGE_PROMPT


def test_knowledge_prompt_distinguishes_remember_page_from_remember():
    """The two tools do different things and the model has to be able to
    tell them apart from the prompt alone: `remember_page` for a page already
    fetched, `remember` for everything else. Losing either name from the
    prompt leaves a tool the model cannot discover a reason to call."""
    from research_team.infrastructure.agent.knowledge_tools import KNOWLEDGE_PROMPT

    assert "`remember_page` commits a page you have fetched" in KNOWLEDGE_PROMPT
    assert "`remember` is for everything else" in KNOWLEDGE_PROMPT


def test_knowledge_prompt_no_longer_asks_for_transcription():
    """This is the instruction the whole by-reference feature exists to
    remove: asking the model to retype a page's text or copy its `url:`,
    `title:` or `date:` lines across by hand. A future edit that reinstated
    it would silently undo the feature while every other test here -- which
    checks what the prompt does say, not what it omits -- stayed green."""
    from research_team.infrastructure.agent.knowledge_tools import KNOWLEDGE_PROMPT

    assert "pass the `url:`, `title:` and `date:` lines" not in KNOWLEDGE_PROMPT
    assert "pass substantial content you have actually read" not in KNOWLEDGE_PROMPT


@pytest.mark.asyncio
async def test_graph_describe_returns_what_the_card_index_matched():
    """The tool exists and reaches `describe`, not `search`.

    Both tools format identically, so a `graph_describe` accidentally wired to
    `search` would return plausible output for a name query and nothing for a
    descriptive one -- which is the failure it exists to fix, dressed as the
    fix. The stub answers the two methods differently so only correct wiring
    passes.
    """
    described = [
        Match(
            entity_id=uuid4(),
            name="Ada Lovelace",
            entity_type="Person",
            relationship_count=1,
        )
    ]
    tools = tools_by_name(StubKnowledge(matches=[], described=described))

    result = await tools["graph_describe"].ainvoke({"query": "who worked with Babbage"})

    assert "Ada Lovelace" in result


@pytest.mark.asyncio
async def test_graph_describe_says_when_there_is_no_card_index():
    """An unwired card corpus is named, not rendered as "no matches".

    A model told "no matching entities" stops asking; one told the index is
    missing can fall back to `graph_search` on a name. Every defect this
    feature can have presents as an empty answer, so the distinction is the
    only thing separating them.
    """
    tools = tools_by_name(
        StubKnowledge(matches=[], described=[], describe_mode=SearchMode.UNAVAILABLE)
    )

    result = await tools["graph_describe"].ainvoke({"query": "anything"})

    assert "unavailable" in result.lower()
    assert "graph_search" in result
