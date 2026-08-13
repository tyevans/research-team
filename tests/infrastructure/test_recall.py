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
    query_key,
    url_key,
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


# ---- normalization is total ----


@pytest.mark.parametrize(
    "url",
    ["http://host:port/x", "http://host:99999/x", "http://host:-1/x"],
)
def test_a_malformed_port_is_returned_rather_than_raised(url: str):
    """`urlsplit(...).port` raises `ValueError` on a port that is not a number
    in range, and this is applied to text the model wrote -- a `fetch` URL, and
    every `uri` in the corpus. A raise here costs the whole turn; a string that
    matches nothing costs one redundant request.
    """
    assert normalize_url(url)


# ---- one store, two kinds of request ----


def test_a_url_keys_differently_as_a_query_than_as_a_page():
    """A bare URL pasted as a search query normalizes to the same string as
    that URL does. One keyspace for both tools would let a `web_search` answer
    a later `fetch` with its snippet list, presented as the page.
    """
    url = "https://arxiv.org/abs/2401.00001"
    assert normalize_query(url) == normalize_url(url)
    assert query_key(url) != url_key(url)


# ---- the parameters that change what a search returns ----


def test_a_search_with_no_parameters_keys_exactly_as_it_always_did():
    """Byte-for-byte, not merely "still distinct". Entries are keyed and read
    within one process, so a changed shape would not corrupt anything -- but
    the unparameterised call is the overwhelming majority of searches, and a
    key that grows a suffix for all of them is a change nobody asked for. This
    fails on any decoration of the plain key.
    """
    assert query_key("Backward Design") == "q:backward design"


@pytest.mark.parametrize(
    "params",
    [
        {"time_range": "year"},
        {"engines": "arxiv"},
        {"categories": "science"},
    ],
)
def test_a_parameter_that_changes_the_answer_changes_the_key(params):
    """SearXNG is not insensitive to these -- changing what it returns is the
    entire reason for sending them. Sharing a key with the unrestricted search
    would hand the model results for a question it did not ask, labelled as
    recalled and therefore trusted.
    """
    assert query_key("backward design", **params) != query_key("backward design")


def test_each_parameter_occupies_its_own_slot_in_the_key():
    """The same word in two different parameters is two different searches.
    A key that concatenated values without saying which field they came from
    would merge these.
    """
    assert query_key("q", engines="news") != query_key("q", categories="news")


def test_two_parameter_values_that_differ_are_two_keys():
    assert query_key("q", time_range="year") != query_key("q", time_range="month")


def test_the_query_is_still_normalized_when_parameters_are_present():
    """Extending the key must not cost the folding it already does; a
    parameterised search that spells its query differently is still the same
    search.
    """
    assert query_key("Backward  Design", time_range="year") == query_key(
        "backward design", time_range="year"
    )


def test_a_parameter_value_cannot_be_forged_from_the_query_text():
    """The suffix is separated by a unit separator, which `normalize_query`
    cannot emit: Python treats \\x1f as whitespace, so `str.split` consumes it
    and the collapse turns it into a space. A query crafted to look like a
    parameter suffix therefore lands in a different key than the parameter
    itself. Fails if the delimiter is ever changed to a printable character.
    """
    assert query_key("q\x1ftime_range=year") != query_key("q", time_range="year")


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
