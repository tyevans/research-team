"""Tests for the extracted course_html_resolvers module."""

from research_team.interfaces.web import course_html
from research_team.interfaces.web.course_html_resolvers import (
    MAX_QUOTE_CHARS,
    CourseReads,
    Passage,
    Resolution,
    _entity_by_name,
    _interval,
    _resolve,
    _resolve_compare,
    _resolve_definition,
    _resolve_evidence,
    _resolve_graph,
    _resolve_timeline,
    entity_by_name,
    interval,
    quote_passage,
    resolve,
    resolve_citations,
    resolve_compare,
    resolve_definition,
    resolve_evidence,
    resolve_graph,
    resolve_timeline,
)


def test_resolver_exports_match_between_modules():
    """Verify that course_html re-exports the exact classes and functions."""
    assert course_html.CourseReads is CourseReads
    assert course_html.Resolution is Resolution
    assert course_html.Passage is Passage
    assert course_html.MAX_QUOTE_CHARS is MAX_QUOTE_CHARS
    assert course_html.quote_passage is quote_passage
    assert course_html.resolve_citations is resolve_citations
    assert course_html._entity_by_name is _entity_by_name is entity_by_name
    assert course_html._interval is _interval is interval
    assert course_html._resolve is _resolve is resolve
    assert course_html._resolve_evidence is _resolve_evidence is resolve_evidence
    assert course_html._resolve_definition is _resolve_definition is resolve_definition
    assert course_html._resolve_graph is _resolve_graph is resolve_graph
    assert course_html._resolve_timeline is _resolve_timeline is resolve_timeline
    assert course_html._resolve_compare is _resolve_compare is resolve_compare


def test_quote_passage_clamping():
    text = "Hello world!"
    passage, truncated = quote_passage(text, 0, 5)
    assert passage == "Hello"
    assert not truncated

    long_text = "a" * (MAX_QUOTE_CHARS + 100)
    passage, truncated = quote_passage(long_text, 0, len(long_text))
    assert len(passage) == MAX_QUOTE_CHARS
    assert truncated


def test_interval_parsing():
    start, end = _interval({"from": "2026-01-01T00:00:00Z", "to": "invalid"})
    assert start is not None
    assert end is None
