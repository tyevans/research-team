"""Serving a citation with the moment it names, when it has one.

`serve_citations` is the first production caller of `locators.resolve` (see
that module's docstring, which named a citation renderer as the intended
caller before one existed). It sits between the two citation producers --
`DefinitionService` and, at the web layer, `read_graph_definition` -- and a
corpus read model, so it is exercised here against a fake `CorpusReadPort`
rather than either producer.
"""

import json
from uuid import uuid4

from research_team.application.corpus_read import StoredDocument
from research_team.application.entity_definitions import (
    Citation,
    ServedCitation,
    serve_citations,
)
from research_team.domain.corpus import TextRecord


def _map(*segments: tuple[int, int, dict[str, object]]) -> str:
    """A locator map in the shape `MediaPerceiver` writes it."""
    return json.dumps(
        [
            {"char_start": start, "char_end": end, "locator": locator}
            for start, end, locator in segments
        ]
    )


TRANSCRIPT_MAP = _map(
    (0, 100, {"kind": "time", "start_s": 0.0, "end_s": 200.0}),
    (100, 200, {"kind": "time", "start_s": 252.0, "end_s": 400.0}),
)


class FakeReader:
    """`CorpusReadPort` over a fixed `{source_id: StoredDocument}` mapping.

    Only `read_document` is implemented -- `serve_citations` calls nothing
    else, and a fake that implemented the rest would be dead code nobody
    could tell was untested.
    """

    def __init__(self, documents: dict[str, StoredDocument]) -> None:
        self._documents = documents
        self.reads: list[str] = []

    async def read_document(
        self, source_id: str, *, include_dropped: bool = False
    ) -> StoredDocument | None:
        self.reads.append(source_id)
        return self._documents.get(source_id)


def _document(text: str, locator_map: str | None) -> StoredDocument:
    return StoredDocument(
        record=TextRecord(source_id="unused", sha256="0" * 64, char_count=len(text)),
        text=text,
        locator_map=locator_map,
    )


PROJECT_ID = uuid4()


async def test_a_citation_into_a_transcript_carries_the_second_it_came_from() -> None:
    video = "video-1"
    reader = FakeReader({video: _document("x" * 200, TRANSCRIPT_MAP)})
    served = await serve_citations(reader, [Citation(source_id=video, start=100, end=140)])
    assert served == [ServedCitation(source_id=video, start=100, end=140, at_seconds=252.0)]


async def test_a_citation_into_a_text_source_is_unchanged() -> None:
    """Text sources have no locator map. This is the majority case -- every
    text source, today and always -- not an edge case, and a design that
    treated a missing map as an error would break every existing citation in
    order to make media ones work.
    """
    article = "article-1"
    reader = FakeReader({article: _document("hello world", None)})
    served = await serve_citations(reader, [Citation(source_id=article, start=0, end=10)])
    assert served == [ServedCitation(source_id=article, start=0, end=10, at_seconds=None)]


async def test_a_citation_into_an_unknown_source_is_unchanged() -> None:
    """`read_document` answers `None` for a source this project has no such
    id for -- the same "no map" outcome as a text source, not a distinct
    failure `serve_citations` has to raise on.
    """
    reader = FakeReader({})
    served = await serve_citations(reader, [Citation(source_id="ghost", start=0, end=5)])
    assert served == [ServedCitation(source_id="ghost", start=0, end=5, at_seconds=None)]


async def test_a_citation_touching_no_segment_is_unchanged() -> None:
    """A source with a map, but a span the map does not cover -- `resolve`
    answers `()`, and that reads as "no moment", the same as no map at all.
    """
    video = "video-1"
    reader = FakeReader({video: _document("x" * 200, TRANSCRIPT_MAP)})
    served = await serve_citations(reader, [Citation(source_id=video, start=500, end=520)])
    assert served == [ServedCitation(source_id=video, start=500, end=520, at_seconds=None)]


async def test_the_same_source_is_read_once_for_two_citations() -> None:
    """A definition or an answer commonly cites the same source more than
    once; a second `read_document` for it would be work whose result cannot
    differ.
    """
    video = "video-1"
    reader = FakeReader({video: _document("x" * 200, TRANSCRIPT_MAP)})
    await serve_citations(
        reader,
        [
            Citation(source_id=video, start=0, end=10),
            Citation(source_id=video, start=100, end=140),
        ],
    )
    assert reader.reads == [video]


async def test_a_span_crossing_two_time_segments_carries_the_first() -> None:
    """The spec's "Seeking" section: only the first `TimeSpan` is carried.
    A citation denotes where the quoted text starts, which is where a reader
    would seek to -- not the interval the quote happens to span.
    """
    video = "video-1"
    reader = FakeReader({video: _document("x" * 200, TRANSCRIPT_MAP)})
    served = await serve_citations(reader, [Citation(source_id=video, start=50, end=150)])
    assert served[0].at_seconds == 0.0
