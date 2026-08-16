"""What a kept page is called, and why the name may not be its URL.

Every one of these fails with `source_id_for_url` reverted to returning the
url unchanged, which is what `composition.py`'s `keep` did until the console
could not open a single page it had kept: `{source_id}` is one path segment,
uvicorn percent-decodes the path before Starlette routes it, and a `%2F` the
browser sent arrives as a real separator. The route never matches, so the
answer is Starlette's bare `{"detail":"Not Found"}` rather than the handler's
own 404 -- the two are distinguishable, and `test_a_url_id_never_reaches_the
_handler` in `tests/interfaces/test_document_routes.py` is where that
distinction is pinned.
"""

import pytest

from research_team.application.knowledge import SOURCE_ID_LIMIT, source_id_for_url

ROMAN = "https://en.wikipedia.org/wiki/Roman_monarchy"


def test_a_kept_url_becomes_one_path_segment():
    """The whole point: no separator survives into the id.

    Asserts the absence of `/` rather than the exact spelling, because the
    spelling is a readability choice and this is the correctness one. Fails
    against the old `source_id=url`.
    """
    assert "/" not in source_id_for_url(ROMAN)


def test_the_id_is_readable_rather_than_only_a_digest():
    """A digest alone would be correct and unusable.

    The id is what a reader sees in the console's URL and what the model is
    told to cite, so it keeps the host and path. Named separately from the
    test above so a future change that trades readability away fails on the
    trade rather than silently on the assertion it happened to share.
    """
    assert source_id_for_url(ROMAN).startswith("en-wikipedia-org-wiki-roman-monarchy")


def test_two_urls_that_slug_alike_still_differ():
    """Slugging alone collides; the digest is what stops it.

    `?page=1` and `?page=2` survive slugging, but a long URL truncated to the
    cap need not -- so the digest is taken over the *whole* url and appended
    after truncation. Fails if the digest is dropped or is computed over the
    truncated slug.
    """
    stem = "https://example.com/" + "a" * (SOURCE_ID_LIMIT * 2)
    assert source_id_for_url(stem + "?page=1") != source_id_for_url(stem + "?page=2")


def test_the_id_is_capped():
    """A URL is unbounded and this becomes a database key and a URL segment."""
    assert len(source_id_for_url("https://example.com/" + "a" * 500)) <= SOURCE_ID_LIMIT


def test_the_same_url_gives_the_same_id():
    """Deterministic, because `keep` runs again on every re-fetch.

    A random component would store one document per fetch of the same page
    instead of recognising it, which `_store_document`'s digest check could
    not catch -- that check compares bytes *under a given source_id*.
    """
    assert source_id_for_url(ROMAN) == source_id_for_url(ROMAN)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a b/c",  # a space
        "https://example.com/%C3%A9",  # already percent-encoded
        "https://example.com/a#frag",  # `#` collides with DERIVED_SUFFIX
        "https://example.com/",  # nothing but a host
        "https://example.com",  # not even a trailing slash
    ],
)
def test_awkward_urls_still_give_a_usable_id(url):
    """No empty ids, and nothing that needs escaping to sit in a path.

    `#` is called out because `derived_source_id` appends `#perceived` to
    build a transcript's id (`application/perception.py`); a parent id that
    already contains `#` makes that suffix ambiguous.
    """
    got = source_id_for_url(url)
    assert got
    assert got.strip("-") == got
    assert not (set(got) & set("/:#?& %"))
