"""The HTTP routes over media proposals.

Composed the way `test_ontology_routes.py` is -- `build_application` gives a
real `media_proposals` runner and `media_proposal_repository` over the same
database, so `GET .../media-proposals` reads what the write routes actually
wrote rather than a double's approximation of it. The chain's own text and
search calls are stubbed with the fakes `test_media_curation.py` already
built (`FakeTextPort`, `FakeSearchPort`) and a `topics` callable answering
one canned `TopicDetail` -- this file is about the routes' status codes and
wiring, not the chain's parsing, which that module already covers.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application
from research_team.interfaces.web.app import create_app
from tests.application.test_media_curation import (
    FakeSearchPort,
    FakeTextPort,
    FakeTopicPort,
    _judgements_json,
    _needs_json,
    _result,
    _terms_json,
    _topic_detail,
)


def _api(application, *, text=None, search=None, topics=None):
    return create_app(
        application.service,
        application.feed,
        application.turns,
        media_proposals=application.media_proposals,
        media_proposal_repository=application.media_proposal_repository,
        curation_text=text,
        curation_search=search,
        topics=topics,
    )


@pytest.fixture
async def application(db_path):
    app = build_application(db_path=db_path)
    await app.start()
    try:
        yield app
    finally:
        await app.close()


async def _new_project(client: AsyncClient) -> str:
    created = await client.post("/api/projects", json={"name": f"media-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


def _chain_ports(topic_id: UUID):
    """One need, one candidate that survives judging -- enough for `curate`
    to write a `MediaProposed` a route test can then act on.
    """
    text = FakeTextPort([_needs_json(1), _terms_json(1), _judgements_json(1)])
    search = FakeSearchPort([_result("https://example.com/pic.jpg")])
    topics = lambda project_id: FakeTopicPort({topic_id: _topic_detail(topic_id)})  # noqa: E731
    return text, search, topics


@pytest.fixture
async def proposed(application):
    """A project with one proposal already on the log, plus the client and
    ids every test below needs -- the `accept`/`reject`/`ignore` routes all
    need a real `proposal_id` to act on, not a made-up one.
    """
    topic_id = uuid4()
    text, search, topics = _chain_ports(topic_id)
    api = _api(application, text=text, search=search, topics=topics)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = await _new_project(client)
        run = await client.post(
            f"/api/projects/{project_id}/topics/{topic_id}/media-proposals"
        )
        assert run.status_code == 202
        listed = (await client.get(f"/api/projects/{project_id}/media-proposals")).json()
        proposal_id = listed[0]["proposals"][0]["proposal_id"]
        yield client, project_id, proposal_id


async def test_running_the_chain_answers_202_with_outcome_counts(application):
    topic_id = uuid4()
    text, search, topics = _chain_ports(topic_id)
    api = _api(application, text=text, search=search, topics=topics)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = await _new_project(client)

        response = await client.post(
            f"/api/projects/{project_id}/topics/{topic_id}/media-proposals"
        )

        assert response.status_code == 202
        body = response.json()
        assert body["needs"] == 1
        assert body["candidates"] == 1


async def test_running_the_chain_without_curation_wired_answers_503(application):
    api = _api(application)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = await _new_project(client)

        response = await client.post(
            f"/api/projects/{project_id}/topics/{uuid4()}/media-proposals"
        )

        assert response.status_code == 503


async def test_listing_groups_proposals_by_need_and_labels_the_group(proposed):
    client, project_id, _proposal_id = proposed

    response = await client.get(f"/api/projects/{project_id}/media-proposals")

    assert response.status_code == 200
    groups = response.json()
    assert len(groups) == 1
    assert groups[0]["need_description"]
    assert len(groups[0]["proposals"]) == 1


async def test_accept_answers_202(proposed):
    client, project_id, proposal_id = proposed

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/accept"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


async def test_a_second_accept_is_refused_with_409_not_500(proposed):
    """A `CommandRejectedError` this route does not catch reaches the caller
    as a 500 with no message. `decide`
    refuses a second `AcceptMediaProposal` on an already-accepted proposal --
    "a closed decision is closed" -- and this is the route's own test of the
    mapping the brief calls out by name, not a copy of `test_document_routes`'s
    equivalent for a different aggregate.
    """
    client, project_id, proposal_id = proposed
    first = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/accept"
    )
    assert first.status_code == 202

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/accept"
    )

    assert response.status_code == 409
    assert response.json()["detail"]


async def test_accept_of_an_unknown_proposal_is_409_not_500(proposed):
    client, project_id, _proposal_id = proposed

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/does-not-exist/accept"
    )

    assert response.status_code == 409


async def test_reject_answers_200_and_accepts_a_note(proposed):
    client, project_id, proposal_id = proposed

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/reject",
        json={"note": "wrong century"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


async def test_reject_without_a_body_defaults_the_note_to_empty(proposed):
    client, project_id, proposal_id = proposed

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/reject"
    )

    assert response.status_code == 200


async def test_reject_of_an_already_rejected_proposal_is_409_not_500(proposed):
    client, project_id, proposal_id = proposed
    await client.post(f"/api/projects/{project_id}/media-proposals/{proposal_id}/reject")

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/reject"
    )

    assert response.status_code == 409


async def test_ignore_by_asset_moves_the_url_into_the_ignored_assets_list(proposed):
    client, project_id, proposal_id = proposed

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/ignore",
        json={"grain": "asset"},
    )

    assert response.status_code == 200
    ignored = (await client.get(f"/api/projects/{project_id}/ignored")).json()
    assert ignored["assets"] == ["https://example.com/pic.jpg"]
    assert ignored["hosts"] == []


async def test_ignore_by_host_moves_the_host_into_the_ignored_hosts_list(proposed):
    client, project_id, proposal_id = proposed

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/ignore",
        json={"grain": "host"},
    )

    assert response.status_code == 200
    ignored = (await client.get(f"/api/projects/{project_id}/ignored")).json()
    assert ignored["hosts"] == ["example.com"]


async def test_ignore_of_an_unknown_proposal_is_404(proposed):
    client, project_id, _proposal_id = proposed

    response = await client.post(
        f"/api/projects/{project_id}/media-proposals/does-not-exist/ignore",
        json={"grain": "asset"},
    )

    assert response.status_code == 404


async def test_unignore_removes_an_asset_from_the_ignored_list(proposed):
    client, project_id, proposal_id = proposed
    await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/ignore",
        json={"grain": "asset"},
    )
    key = "https://example.com/pic.jpg"

    response = await client.delete(f"/api/projects/{project_id}/ignored/asset/{key}")

    assert response.status_code == 200
    ignored = (await client.get(f"/api/projects/{project_id}/ignored")).json()
    assert ignored["assets"] == []


async def test_unignore_removes_a_host_from_the_ignored_list(proposed):
    client, project_id, proposal_id = proposed
    await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/ignore",
        json={"grain": "host"},
    )

    response = await client.delete(f"/api/projects/{project_id}/ignored/host/example.com")

    assert response.status_code == 200
    ignored = (await client.get(f"/api/projects/{project_id}/ignored")).json()
    assert ignored["hosts"] == []


async def test_get_ignored_reports_both_lists_empty_for_a_fresh_project(application):
    api = _api(application)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = await _new_project(client)

        response = await client.get(f"/api/projects/{project_id}/ignored")

        assert response.status_code == 200
        assert response.json() == {"assets": [], "hosts": []}


async def test_a_route_over_an_unknown_project_is_404(application):
    api = _api(application)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/projects/{uuid4()}/media-proposals")

        assert response.status_code == 404
