"""The four write routes over a project's corpus.

Built through the real `CorpusEditor` and a real `Corpus` aggregate, over a
started application, rather than through doubles like
`test_extraction_routes.py`: the interesting behaviour here is `CorpusEditor`'s
own -- the existence check, the aggregate's refusals, the fold that turns a
restore into a fresh record -- and stubbing it out would leave these tests
asserting that the routes forward calls correctly, which is a smaller and less
useful claim.
"""

import hashlib
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application.knowledge import MAX_DOCUMENT_CHARS
from research_team.composition import build_application as _build_application
from research_team.domain.corpus import StoreSourceMedia
from research_team.interfaces.web import app as app_module
from research_team.interfaces.web.app import create_app


async def _started(**kwargs):
    application = _build_application(**kwargs)
    await application.start()
    return application


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        editor=application.editor,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


@pytest.fixture
async def app_without_corpus(app_and_client):
    """Neither `corpus` nor `editor` wired -- see the RULING in the brief.

    `_editor()` only checks `editor`, and the two are separately injected, so
    a fixture that supplied one and not the other would exercise a route that
    fails further in (reading back through `_reader`, which would then be the
    thing 503ing) rather than the write-side check this test means to cover.
    """
    application, _ = app_and_client
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=None,
        editor=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as unwired:
        project = await _new_project(unwired)
        yield unwired, project


async def _new_project(client: AsyncClient) -> str:
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


async def test_upload_stores_a_document(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)

    response = await client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": "s1", "text": "hello", "title": "Hello"},
    )

    assert response.status_code == 201
    assert response.json()["source_id"] == "s1"
    listed = (await client.get(f"/api/projects/{project}/sources")).json()
    assert [row["source_id"] for row in listed] == ["s1"]


async def test_upload_refuses_an_id_the_corpus_holds(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "other"}
    )

    assert response.status_code == 409


async def test_a_patch_changes_the_title_and_leaves_the_text(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": "s1", "text": "hello", "title": "Typo"},
    )

    response = await client.patch(
        f"/api/projects/{project}/sources/s1", json={"title": "Fixed"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Fixed"
    read_back = (await client.get(f"/api/projects/{project}/sources/s1")).json()
    assert read_back["text"] == "hello"


async def test_a_patch_over_the_length_cap_is_400_not_500(app_and_client):
    """`_store`'s length cap is the only guard `revise` has -- `decide` has
    no opinion on document size -- and `revise_source` used to catch only
    `UnknownDocument`, so this was an unhandled `KnowledgeError` and a 500
    rather than the 400 `upload_source` already answers for the same error.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.patch(
        f"/api/projects/{project}/sources/s1",
        json={"text": "x" * (MAX_DOCUMENT_CHARS + 1)},
    )

    assert response.status_code == 400


async def test_a_patch_on_an_unknown_source_is_404(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.patch(
        f"/api/projects/{project}/sources/missing", json={"title": "x"}
    )

    assert response.status_code == 404


async def test_drop_excludes_the_document_and_restore_puts_it_back(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    dropped = await client.post(
        f"/api/projects/{project}/sources/s1/drop", json={"reason": "off topic"}
    )
    assert dropped.status_code == 200
    assert (await client.get(f"/api/projects/{project}/sources")).json() == []

    restored = await client.post(f"/api/projects/{project}/sources/s1/restore", json={})
    assert restored.status_code == 200
    assert restored.json()["dropped_reason"] is None
    assert len((await client.get(f"/api/projects/{project}/sources")).json()) == 1


async def test_drop_refuses_a_blank_reason(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.post(
        f"/api/projects/{project}/sources/s1/drop", json={"reason": "  "}
    )

    assert response.status_code == 409


async def test_restore_refuses_a_document_that_is_not_dropped(app_and_client):
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.post(f"/api/projects/{project}/sources/s1/restore", json={})

    assert response.status_code == 409


async def test_a_dropped_document_can_still_be_read(app_and_client):
    """The console lists dropped rows and lets you open one.

    Red before `read_source` passed `include_dropped=True`: the GET answered
    404 and the drawer someone had just dropped from rendered an error box,
    with the Restore button above text it could no longer show.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )
    await client.post(f"/api/projects/{project}/sources/s1/drop", json={"reason": "off topic"})

    response = await client.get(f"/api/projects/{project}/sources/s1")

    assert response.status_code == 200
    assert response.json()["text"] == "hello"
    assert response.json()["dropped_reason"] == "off topic"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/sources", {"source_id": "s1", "text": "hello"}),
        ("patch", "/sources/s1", {"title": "x"}),
        ("post", "/sources/s1/drop", {"reason": "off topic"}),
        ("post", "/sources/s1/restore", {}),
    ],
)
async def test_the_routes_answer_503_with_no_corpus_configured(
    app_without_corpus, method, path, body
):
    """`_reader` already answers this for the read routes; the write routes
    have to make the same check rather than failing further in.

    All four rather than the create alone: they share one `_editor()`, so the
    risk of a divergence is low, but a route added later that forgets the call
    is exactly what a test named for "the routes" should catch.
    """
    client, project = app_without_corpus

    response = await getattr(client, method)(f"/api/projects/{project}{path}", json=body)

    assert response.status_code == 503


async def test_upload_works_on_a_project_no_earlier_call_has_touched(app_and_client):
    """A second project, seeded by nothing.

    `CLAUDE.md` records the failure this guards: a request path that stopped
    opening the project answered 503 on the first call for a newly-touched
    project and succeeded on every one after, because some earlier test in the
    same process had already opened it. Every other test in this file arranges
    through the route under test and cannot see that.
    """
    _app, client = app_and_client
    await _new_project(client)  # the project every other assertion would run against
    untouched = await _new_project(client)

    response = await client.post(
        f"/api/projects/{untouched}/sources",
        json={"source_id": "s1", "text": "hello"},
    )

    assert response.status_code == 201


async def _upload_media(
    client: AsyncClient,
    project: str,
    source_id: str,
    payload: bytes,
    media_type: str = "video/mp4",
    filename: str = "talk.mp4",
):
    return await client.post(
        f"/api/projects/{project}/sources/media",
        files={"file": (filename, payload, media_type)},
        data={"source_id": source_id},
    )


async def test_uploading_media_stores_a_row_that_lists(app_and_client):
    """Asserts the listing, not the 201.

    An event no projection handles counts as APPLIED here, so a 201 is
    returned by a build whose media projection was never registered; the row
    is what is not. Red before `upload_media` existed: 405, the path matching
    no route.
    """
    _app, client = app_and_client
    project = await _new_project(client)

    response = await _upload_media(client, project, "v1", b"\x00\x00\x00\x18ftypmp42")

    assert response.status_code == 201
    listed = (await client.get(f"/api/projects/{project}/sources")).json()
    assert [row["source_id"] for row in listed if row["kind"] == "media"] == ["v1"]
    assert listed[0]["media_type"] == "video/mp4"
    assert listed[0]["byte_count"] == 12


async def test_media_uploaded_without_a_source_id_is_named_by_its_filename(app_and_client):
    """A person uploading `keynote.mp4` has already named it.

    Would fail on a route that made `source_id` required (422) or defaulted it
    to something opaque like the digest.
    """
    _app, client = app_and_client
    project = await _new_project(client)

    response = await client.post(
        f"/api/projects/{project}/sources/media",
        files={"file": ("keynote.mp4", b"bytes", "video/mp4")},
    )

    assert response.status_code == 201
    assert response.json()["source_id"] == "keynote.mp4"


async def test_an_octet_stream_upload_is_sniffed_rather_than_stored_as_sent(app_and_client):
    """Browsers send `application/octet-stream` for anything the OS has no
    association for -- `.mkv` and `.webm` on a bare machine.

    Stored verbatim, the content route would answer with a type no `<video>`
    plays, and nothing re-sniffs a stored blob. Would fail on a route that
    passed `file.content_type` straight through.
    """
    _app, client = app_and_client
    project = await _new_project(client)

    response = await _upload_media(
        client,
        project,
        "v1",
        b"\x00\x00\x00\x20ftypisom",
        media_type="application/octet-stream",
    )

    assert response.status_code == 201
    assert response.json()["media_type"] == "video/mp4"


async def test_content_streams_the_bytes_back_with_their_type(app_and_client):
    """The actual bytes, not merely a 200: a route that streamed an empty
    iterator would answer 200 with a zero-byte body and look identical."""
    _app, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"payload")

    response = await client.get(f"/api/projects/{project}/sources/v1/content")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == b"payload"


async def test_a_range_request_answers_206_with_only_that_range(app_and_client):
    """Ahead of the citation slice that needs it, and argued for in the spec:
    a `<video>` seeking to 4:12 issues a range request, and without one
    Chromium downloads the whole file before it will play.

    The byte arithmetic is what this holds: an inclusive end read as exclusive
    truncates every seek by one byte, which a player reports as a corrupt
    stream rather than as an off-by-one.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"0123456789")

    response = await client.get(
        f"/api/projects/{project}/sources/v1/content", headers={"Range": "bytes=2-5"}
    )

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"


@pytest.mark.parametrize(
    "header,expected,content_range",
    [
        # Both ends, at the very edges -- the two places an off-by-one hides.
        ("bytes=0-0", b"0", "bytes 0-0/10"),
        ("bytes=9-9", b"9", "bytes 9-9/10"),
        # Open-ended: what a `<video>` sends first, before it knows the length.
        ("bytes=7-", b"789", "bytes 7-9/10"),
        # Suffix: how a player finds an MP4's trailing `moov` atom.
        ("bytes=-3", b"789", "bytes 7-9/10"),
        # An end past the last byte is clamped, not refused.
        ("bytes=8-99", b"89", "bytes 8-9/10"),
    ],
)
async def test_the_range_forms_a_browser_actually_sends(
    app_and_client, header, expected, content_range
):
    """Five forms, each of which a real player emits, against a file whose
    every byte is distinguishable. Would fail on a parser that handled only
    `bytes=start-end`: the open-ended and suffix forms would silently return
    the whole file with a 200."""
    _app, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"0123456789")

    response = await client.get(
        f"/api/projects/{project}/sources/v1/content", headers={"Range": header}
    )

    assert response.status_code == 206
    assert response.content == expected
    assert response.headers["content-range"] == content_range


async def test_a_range_past_the_end_answers_416_with_the_real_length(app_and_client):
    """416 rather than 200-with-everything: the client asked for bytes that do
    not exist, and a 200 would silently hand it different ones. The
    `Content-Range: bytes */10` is what lets it correct itself in one round
    trip instead of guessing."""
    _app, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"0123456789")

    response = await client.get(
        f"/api/projects/{project}/sources/v1/content", headers={"Range": "bytes=50-60"}
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"


async def test_an_unparseable_range_is_ignored_rather_than_refused(app_and_client):
    """RFC 9110: a recipient that cannot satisfy a Range must ignore it and
    answer 200 with the whole representation. Would fail on a parser that
    answered 400 for a header a client was entitled to send."""
    _app, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"0123456789")

    response = await client.get(
        f"/api/projects/{project}/sources/v1/content", headers={"Range": "furlongs=1-2"}
    )

    assert response.status_code == 200
    assert response.content == b"0123456789"


async def test_a_record_whose_bytes_are_gone_answers_410(app_and_client):
    """410 Gone, not 404. The source exists and its bytes do not, and an
    operator told 404 goes looking for an ingest that never happened."""
    application, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"payload")

    digest = hashlib.sha256(b"payload").hexdigest()
    application.blob_store._path(digest).unlink()

    response = await client.get(f"/api/projects/{project}/sources/v1/content")

    assert response.status_code == 410


async def test_content_for_a_text_source_answers_404(app_and_client):
    """The route serves bytes from the blob store; a text source has none
    there. 404 rather than 410 -- nothing is missing, this is the wrong route
    for that source. Would fail on a handler that read the corpus row without
    discriminating on kind and then found no blob for a text digest, which is
    the shape that answers 410 for both."""
    _app, client = app_and_client
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = await client.get(f"/api/projects/{project}/sources/s1/content")

    assert response.status_code == 404


async def test_content_for_an_unknown_source_answers_404(app_and_client):
    """`read_media` answering `None` is 404, not the 410 a dangling reference
    gets: nothing was ever stored under this id.

    **This test was not proven red**, and the caveat belongs here rather than
    only in a report nobody reopens. Against a build with no content route at
    all it passes, because a missing route is also a 404 -- so it cannot
    witness the route's existence. What it does hold is the discrimination:
    a handler that answered 410 for every absent blob, not knowing whether the
    record was there, would go red on this and stay green on
    `test_a_record_whose_bytes_are_gone_answers_410` beside it.
    """
    _app, client = app_and_client
    project = await _new_project(client)

    response = await client.get(f"/api/projects/{project}/sources/nothing/content")

    assert response.status_code == 404


async def test_a_suffix_range_against_an_empty_blob_answers_416(app_and_client):
    """A zero-byte source is uploadable, so a range against one is reachable.

    Would fail on a parser whose suffix branch returned before the
    against-the-length guard: `bytes=-3` on a zero-byte blob computes
    `(0, -1)` and the response carries `content-range: bytes 0--1/0`, which is
    not a valid `Content-Range` and which a strict client may treat as a
    broken response. 416 with `bytes */0` is the answer that says what is
    actually true.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    upload = await _upload_media(client, project, "v1", b"", filename="empty.mp4")
    assert upload.status_code == 201

    response = await client.get(
        f"/api/projects/{project}/sources/v1/content", headers={"Range": "bytes=-3"}
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */0"


@pytest.mark.parametrize("header", ["bytes=2-1", "bytes=9-0"])
async def test_an_end_below_the_start_is_ignored_rather_than_refused(app_and_client, header):
    """RFC 9110 §14.1.1: a `last-byte-pos` below `first-byte-pos` makes the
    byte-range-spec *invalid*, and an invalid ranges-specifier must be
    ignored -- 200 with the whole representation.

    Only a range at or past the end is genuinely unsatisfiable. Would fail on
    a parser that folded the two together into one 416, which is what this
    did until review: the function's own docstring already promised to ignore
    anything it did not understand, so the code contradicted its
    documentation.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"0123456789")

    response = await client.get(
        f"/api/projects/{project}/sources/v1/content", headers={"Range": header}
    )

    assert response.status_code == 200
    assert response.content == b"0123456789"


async def test_an_upload_over_the_ceiling_is_refused_mid_stream(app_and_client, monkeypatch):
    """413, and nothing left on disk.

    The limit is monkeypatched rather than exercised with two real gigabytes.
    What this would fail on is a ceiling checked *after* `put` returns: the
    status code would still be 413 and the blob would be sitting under the
    root, which is the whole thing a ceiling exists to prevent -- so the
    assertion is the directory, not the status alone.
    """
    application, client = app_and_client
    project = await _new_project(client)
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 4)

    response = await _upload_media(client, project, "v1", b"far too many bytes")

    assert response.status_code == 413
    root = application.blob_store._root
    assert not [path for path in root.rglob("*") if path.is_file()]
    assert (await client.get(f"/api/projects/{project}/sources")).json() == []


async def test_media_reads_from_a_project_the_fixture_never_touched(app_and_client):
    """A path exercised from a fixture that did not make the call under test.

    The entity-definitions incident: six tests missed a missing `graphs.open`
    because every fixture seeded through it, so from the fixture's point of
    view the project was always open. Here the equivalent is a media record
    whose bytes the fixture never wrote -- the event goes straight onto the
    corpus aggregate, bypassing `store_media` and therefore the blob store
    entirely. The answer must be 410, because the record is real and the bytes
    were never there; a route that reached 200 (or blew up) would be one whose
    every other test was arranged through the very call it was testing.
    """
    application, client = app_and_client
    await _new_project(client)  # the project every other assertion would run against
    untouched = UUID(await _new_project(client))

    corpus = await application.editor._corpus.load_or_create(untouched)
    corpus.execute(
        StoreSourceMedia(
            corpus_id=untouched,
            source_id="ghost",
            sha256="0" * 64,
            media_type="video/mp4",
            byte_count=7,
        )
    )
    await application.editor._corpus.save(corpus)
    await application.corpus_caught_up()

    response = await client.get(f"/api/projects/{untouched}/sources/ghost/content")

    assert response.status_code == 410


async def test_the_media_routes_answer_503_with_no_corpus_configured(app_without_corpus):
    """`_editor()` and `_reader()` are separate checks, and the media routes
    use one each -- upload the editor, content the reader. A route that
    forgot either would fail further in with a 500."""
    client, project = app_without_corpus

    upload = await client.post(
        f"/api/projects/{project}/sources/media",
        files={"file": ("talk.mp4", b"bytes", "video/mp4")},
    )
    content = await client.get(f"/api/projects/{project}/sources/v1/content")

    assert upload.status_code == 503
    assert content.status_code == 503


async def test_a_dropped_media_source_restores(app_and_client):
    """Restore reaches media, not only text.

    Red before the media branch in `CorpusEditor.restore`: 404, because
    `restore` resolved through `read_document`, which answers `None` for a
    media source by design. The assertion is `dropped_reason` back to `None`
    in the *listing* -- a 200 alone would pass against a restore that stored
    nothing, since an event no projection handles still counts as applied.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"0123456789")
    dropped = await client.post(
        f"/api/projects/{project}/sources/v1/drop", json={"reason": "wrong take"}
    )
    assert dropped.status_code == 200

    response = await client.post(f"/api/projects/{project}/sources/v1/restore", json={})

    assert response.status_code == 200
    assert response.json()["dropped_reason"] is None
    listed = (await client.get(f"/api/projects/{project}/sources")).json()
    assert [row["source_id"] for row in listed] == ["v1"]


async def test_patching_a_media_source_changes_its_metadata(app_and_client):
    """PATCH reaches media, and leaves the bytes alone.

    Red before the media branch in `CorpusEditor.revise`: 404, same root cause
    as the restore case above. `sha256` and `byte_count` are asserted
    unchanged because the re-store carries them from the stored record -- a
    branch that recomputed or defaulted either would answer 200 over a record
    that no longer points at its own bytes.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    stored = (await _upload_media(client, project, "v1", b"0123456789")).json()

    response = await client.patch(
        f"/api/projects/{project}/sources/v1",
        json={"title": "Keynote, second cut"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Keynote, second cut"
    assert response.json()["sha256"] == stored["sha256"]
    assert response.json()["byte_count"] == stored["byte_count"]
    assert (await client.get(f"/api/projects/{project}/sources/v1/content")).status_code == 200


async def test_patching_text_onto_a_media_source_is_refused(app_and_client):
    """The one field a media revise cannot take.

    `decide`'s `_kind_of` guard would refuse `StoreSourceDocument` over a
    media id anyway, so nothing here could turn a recording into a document;
    this refuses earlier and says why, rather than answering 409 with the
    aggregate's wording or -- worse -- 200 having silently ignored the field.
    Red against a branch that dropped `text` on the floor: 200.
    """
    _app, client = app_and_client
    project = await _new_project(client)
    await _upload_media(client, project, "v1", b"0123456789")

    response = await client.patch(
        f"/api/projects/{project}/sources/v1", json={"text": "a transcript"}
    )

    assert response.status_code == 400
