"""What `fetch` retains for `remember_page`, as against what it shows the model."""

from research_team.infrastructure.agent.recall import PageMemo, RetainedPage


def test_a_retained_page_comes_back_whole() -> None:
    """The retained text is the document, not the excerpt the model was shown.

    This is the point of the store: `Recall` holds the truncated string, and a
    corpus that could only ever receive that string was capped at the context
    budget rather than at its own limit.
    """
    memo = PageMemo(stamp=lambda: "2026-08-10T12:00:00+00:00")
    memo.put("https://example.com/a", text="whole document", uri="https://example.com/a")

    retained = memo.get("https://example.com/a")

    assert retained is not None
    assert retained.text == "whole document"


def test_provenance_is_stored_not_reparsed() -> None:
    """title and published_at arrive as fields, so nothing has to read them back
    out of a citation header a page's own prose could imitate."""
    memo = PageMemo(stamp=lambda: "2026-08-10T12:00:00+00:00")
    memo.put(
        "https://example.com/a",
        text="body",
        uri="https://example.com/a",
        title="A Paper",
        published_at="2026-01-02",
    )

    retained = memo.get("https://example.com/a")

    assert retained == RetainedPage(
        text="body",
        uri="https://example.com/a",
        title="A Paper",
        published_at="2026-01-02",
        fetched_at="2026-08-10T12:00:00+00:00",
    )


def test_fetched_at_is_stamped_at_write_time() -> None:
    """A wall-clock stamp, because the expiry clock is `time.monotonic` and has
    no zero to convert an age against. Without this the field cannot be filled
    honestly at ingest, and a guessed timestamp is worse than the None it
    replaces."""
    stamps = iter(["2026-08-10T12:00:00+00:00", "2026-08-10T13:00:00+00:00"])
    memo = PageMemo(stamp=lambda: next(stamps))

    memo.put("https://example.com/a", text="a", uri="https://example.com/a")
    memo.put("https://example.com/b", text="b", uri="https://example.com/b")

    first = memo.get("https://example.com/a")
    second = memo.get("https://example.com/b")
    assert first is not None and second is not None
    assert first.fetched_at == "2026-08-10T12:00:00+00:00"
    assert second.fetched_at == "2026-08-10T13:00:00+00:00"


def test_a_url_that_was_never_retained_is_a_miss() -> None:
    memo = PageMemo()

    assert memo.get("https://example.com/missing") is None


def test_equivalent_urls_are_one_entry() -> None:
    """Keyed by `url_key`, so a handle and a corpus hit agree about what the
    same page is. Fails if this grows its own normalization."""
    memo = PageMemo(stamp=lambda: "2026-08-10T12:00:00+00:00")
    memo.put("https://Example.com:443/a#frag", text="body", uri="https://example.com/a")

    assert memo.get("https://example.com/a") is not None


def test_an_expired_page_is_a_miss() -> None:
    """An hour-old handle does not resolve, and that is ordinary operation --
    `remember_page` is expected to say so rather than store nothing quietly."""
    now = 0.0
    memo = PageMemo(ttl_seconds=10.0, clock=lambda: now, stamp=lambda: "t")
    memo.put("https://example.com/a", text="body", uri="https://example.com/a")

    now = 11.0

    assert memo.get("https://example.com/a") is None


def test_the_coldest_entry_is_evicted_when_full() -> None:
    memo = PageMemo(capacity=2, stamp=lambda: "t")
    memo.put("https://example.com/1", text="1", uri="https://example.com/1")
    memo.put("https://example.com/2", text="2", uri="https://example.com/2")
    memo.get("https://example.com/1")
    memo.put("https://example.com/3", text="3", uri="https://example.com/3")

    assert memo.get("https://example.com/2") is None
    assert memo.get("https://example.com/1") is not None
    assert memo.get("https://example.com/3") is not None


def test_a_second_put_replaces_the_first() -> None:
    """A refreshed read supersedes what was retained, so `remember_page` after
    `refresh=True` commits the new bytes rather than the old."""
    memo = PageMemo(stamp=lambda: "t")
    memo.put("https://example.com/a", text="old", uri="https://example.com/a")
    memo.put("https://example.com/a", text="new", uri="https://example.com/a")

    retained = memo.get("https://example.com/a")

    assert retained is not None
    assert retained.text == "new"
