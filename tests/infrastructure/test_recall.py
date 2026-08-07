"""The recall store: what the network tools remember having already served.

The tests that matter most here are the two normalization boundaries. Merging
requests that would have produced different answers is not a cache miss with
extra steps -- it is a wrong answer wearing the label of a right one.
"""

import pytest

from research_team.infrastructure.agent.recall import (
    Recall,
    describe_age,
    normalize_query,
    normalize_url,
)


class _Clock:
    """A hand-wound monotonic clock, so TTL is tested without sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# ---- normalization: what may be merged ----


@pytest.mark.parametrize(
    "a,b",
    [
        ("Backward Design", "backward design"),
        ("backward  design", "backward design"),
        (" backward design ", "backward design"),
        ("backward\tdesign", "backward design"),
    ],
)
def test_queries_a_search_instance_cannot_tell_apart_are_merged(a, b):
    assert normalize_query(a) == normalize_query(b)


# ---- normalization: what may not ----


@pytest.mark.parametrize(
    "a,b",
    [
        ("backward design assessment", "assessment design backward"),
        ("the design of assessment", "design assessment"),
        ("designing assessments", "design assessment"),
    ],
)
def test_queries_an_instance_ranks_differently_are_kept_apart(a, b):
    """Reordering, stopwords and stemming all change what comes back. A memo
    that merges them answers a question the agent did not ask while labelling
    the results as answering the one it did -- which is worse than the
    repeated request it saves, especially against an instance the operator
    runs themselves.
    """
    assert normalize_query(a) != normalize_query(b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("HTTPS://Ex.Example/A", "https://ex.example/A"),
        ("https://ex.example:443/a", "https://ex.example/a"),
        ("http://ex.example:80/a", "http://ex.example/a"),
        ("https://ex.example/a#section", "https://ex.example/a"),
        ("https://ex.example", "https://ex.example/"),
    ],
)
def test_urls_that_address_the_same_resource_are_merged(a, b):
    assert normalize_url(a) == normalize_url(b)


def test_url_paths_keep_their_case():
    """Hosts are case-insensitive and paths are not. Folding the path would
    merge two different pages on any server that serves both.
    """
    assert normalize_url("https://ex.example/A") != normalize_url("https://ex.example/a")


def test_a_query_string_distinguishes_urls():
    assert normalize_url("https://ex.example/s?q=1") != normalize_url(
        "https://ex.example/s?q=2"
    )


# ---- the store ----


def test_what_was_put_comes_back():
    recall = Recall(clock=_Clock())
    recall.put("https://ex.example/a", "body")
    hit = recall.get("https://ex.example/a")
    assert hit is not None
    assert hit.text == "body"


def test_nothing_stored_is_a_miss():
    assert Recall(clock=_Clock()).get("https://ex.example/a") is None


def test_a_hit_reports_the_request_that_produced_it():
    """The safety net under normalization. If the agent asked X and the entry
    was made for Y, the response must be able to say so -- a merge the agent
    can see is a wasted turn, and a merge it cannot see is a wrong answer.
    """
    recall = Recall(clock=_Clock())
    recall.put("Backward Design", "results")
    hit = recall.get("backward  design")
    assert hit is not None
    assert hit.asked == "Backward Design"


def test_a_hit_reports_its_age():
    clock = _Clock()
    recall = Recall(clock=clock)
    recall.put("q", "results")
    clock.now = 90.0
    hit = recall.get("q")
    assert hit is not None
    assert hit.age_seconds == pytest.approx(90.0)


def test_an_entry_past_its_ttl_is_a_miss():
    """The process may be a web server that has been up for days. Without
    expiry, `web_search` -- which has no refresh override -- would serve a
    days-old result set as current for as long as the process lived.
    """
    clock = _Clock()
    recall = Recall(ttl_seconds=60.0, clock=clock)
    recall.put("q", "results")
    clock.now = 61.0
    assert recall.get("q") is None


def test_the_store_evicts_its_least_recently_used_entry():
    """Entries are page bodies of up to 20k chars in a process that may run
    for days. Unbounded, this is a leak sized by how much research is done.
    """
    recall = Recall(capacity=2, clock=_Clock())
    recall.put("a", "1")
    recall.put("b", "2")
    recall.get("a")  # 'a' is now the more recently used of the two
    recall.put("c", "3")
    assert recall.get("b") is None
    assert recall.get("a") is not None
    assert recall.get("c") is not None


def test_putting_the_same_request_twice_replaces_it():
    clock = _Clock()
    recall = Recall(clock=clock)
    recall.put("q", "old")
    clock.now = 10.0
    recall.put("q", "new")
    hit = recall.get("q")
    assert hit is not None
    assert hit.text == "new"
    assert hit.age_seconds == pytest.approx(0.0)


def test_an_explicit_key_separates_matching_from_reporting():
    """`fetch` normalizes URLs and `web_search` normalizes queries, but both
    want the request recorded as the caller wrote it.
    """
    recall = Recall(clock=_Clock())
    recall.put("HTTPS://Ex.Example/A", "body", key=normalize_url("HTTPS://Ex.Example/A"))
    hit = recall.get("https://ex.example/A", key=normalize_url("https://ex.example/A"))
    assert hit is not None
    assert hit.asked == "HTTPS://Ex.Example/A"


# ---- age, in words ----


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.4, "just now"),
        (45.0, "45 seconds ago"),
        (120.0, "2 minutes ago"),
        (7200.0, "2 hours ago"),
    ],
)
def test_age_reads_as_prose(seconds, expected):
    assert describe_age(seconds) == expected
