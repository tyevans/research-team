"""A curated proposal reaching the media-proposal read model, over a composed
application.

Every other test of this projection drives it by hand: the application suite
(`tests/application/test_media_curation.py`) fakes both ports and an
in-memory event store, the read-model suite drives the projection through a
`MediaProposalRunner` it constructed itself. Both stay green in a build where
`composition.py` never constructs a `MediaProposalRunner` at all -- the
curation service would still append its events, nothing would be subscribed
to them, and `eventsource` counts an event no projection handles as APPLIED
rather than rejected (`replay`'s own docstring says so). Nothing raises,
nothing logs, and `/media` for the project answers with an empty list.

That is the exact shape the entity-definitions work shipped once
(`EntityDefinitionRunner` missing from `composition.py` behind a fully green
suite), and it is the shape this file exists to catch. It can only be caught
by asking a composed application, and only by asserting a *row* -- an
assertion that `curate()` returned a count, or raised nothing, passes
identically against a build with the runner unconstructed.

**What is faked, stated rather than implied.** `MediaCurationTextPort` and
`MediaSearchPort` are canned fakes, mirroring the ones
`test_media_curation.py` defines for itself -- nothing here reaches a model
or SearXNG. `TopicReadPort` is also a small fake rather than one read through
`application.topic_readers`: which port answers "what is this topic about" is
not what this file is proving, and building a real topic through
`application.topic_seeder` would spend a fake model call on a fact the
curation chain does not need to be true, only present. What is real is
`application.media_proposal_repository` (`MediaCurationService`'s write side)
and `application.media_proposals` (the read side) -- both built inside
`build_application` from the one event store this instance owns, which is the
seam this file is actually about.
"""

from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.media_curation import (
    MediaCurationService,
    SearchResult,
)
from research_team.application.topic_attention import TopicAttention
from research_team.application.topic_read import SubQuestionView, TopicDetail, TopicView
from research_team.application.topics import TopicSummary
from research_team.composition import build_application

pytestmark = pytest.mark.asyncio

NEEDS_REPLY = '[{"medium": "image", "description": "a map of the city", "why": "orientation"}]'
TERMS_REPLY = '[{"text": "rome forum map", "categories": "images"}]'
JUDGEMENTS_REPLY = '[{"index": 0, "keep": true, "reason": "clear and on topic"}]'

ASSET_URL = "https://example.test/forum-map.jpg"


class FakeCurationText:
    """`MediaCurationTextPort` over three canned replies, one per stage --
    the same shape as `test_media_curation.py`'s `FakeTextPort`, kept local
    rather than imported: this file is about a composed application, and
    pulling a fixture in from another test module would blur which file is
    asserting what.
    """

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)

    @property
    def model_name(self) -> str:
        return "fake-curation-model"

    async def generate(self, prompt: str) -> str:
        return self._replies.pop(0)


class FakeCurationSearch:
    """`MediaSearchPort` returning one fixed candidate for every query."""

    async def search(self, query: str, categories: str) -> tuple[SearchResult, ...]:
        return (
            SearchResult(
                title="a forum map",
                url=ASSET_URL,
                snippet="",
                kind="image",
                asset_url=ASSET_URL,
                detail="",
                thumbnail_url="",
            ),
        )


class FakeCurationTopics:
    """`TopicReadPort` answering one topic id with a fixed `TopicDetail`.

    `list_topics` is unused by `MediaCurationService.curate` and left
    unimplemented, mirroring `test_media_curation.py`'s own fake -- a stub
    that raised would be exercising a claim this file never tests.
    """

    def __init__(self, topic_id, detail: TopicDetail) -> None:
        self._topic_id = topic_id
        self._detail = detail

    async def list_topics(self) -> list[TopicView]:
        raise NotImplementedError("unused by MediaCurationService.curate")

    async def read_topic(self, topic_id) -> TopicDetail | None:
        return self._detail if topic_id == self._topic_id else None


def _topic_detail(topic_id: object) -> TopicDetail:
    summary = TopicSummary(
        topic_id=topic_id,
        question="what did the Roman forum look like?",
        status="open",
        sources=1,
        findings=1,
        open_sub_questions=1,
    )
    return TopicDetail(
        view=TopicView(
            summary=summary, attention=TopicAttention(topic_id=topic_id, findings=())
        ),
        rationale="",
        scope="the layout of the Roman forum",
        sub_questions=(SubQuestionView(key="q1", question="what stood where?", answer=None),),
        source_ids=("s1",),
        findings=("the forum held the senate house and the rostra",),
        contested=False,
    )


@pytest.fixture
async def composed(db_path):
    """A started application, with no model and no project of its own --
    `MediaCurationService` in these tests is built by hand around
    `application.media_proposal_repository`, not routed through anything the
    fixture needs to attach a project for.
    """
    # `model=` a fake rather than the default `None`: `build_application`'s own
    # docstring says an omitted model builds a real `ChatOpenAI` against
    # `config.base_url()` -- construction alone touches no network, but there
    # is no reason for this file to depend on that being true when nothing
    # here exercises the agent's model at all.
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=db_path
    )
    await application.start()
    yield application
    await application.close()


async def test_a_composed_app_stores_a_curated_proposal(composed):
    """The claim the whole runner-wiring task exists to prove.

    Asserts the stored row's `reason` -- the field `MediaProposalRow` carries
    from stage 3's judgement -- rather than that `curate()` returned a count.
    A build with `MediaProposalRunner` unconstructed appends
    `MediaNeedsIdentified` and `MediaProposed` exactly the same, and `curate`
    would return the identical `CurationOutcome(needs=1, candidates=1, ...)`;
    only the row, read back through `application.media_proposals`, tells the
    two builds apart.
    """
    application = composed
    project_id = uuid4()
    topic_id = uuid4()

    service = MediaCurationService(
        text=FakeCurationText([NEEDS_REPLY, TERMS_REPLY, JUDGEMENTS_REPLY]),
        search=FakeCurationSearch(),
        proposals=application.media_proposal_repository,
        topics=FakeCurationTopics(topic_id, _topic_detail(topic_id)),
    )

    outcome = await service.curate(project_id, topic_id)
    assert outcome.candidates == 1

    await application.media_proposals.caught_up()

    (row,) = await application.media_proposals.for_project(project_id)
    assert row.asset_url == ASSET_URL
    assert row.reason == "clear and on topic"


async def test_a_fixture_that_never_calls_media_proposals_start_still_sees_the_row(db_path):
    """The rule from `CLAUDE.md`'s "Read models" section, applied directly: a
    fixture whose arrange phase calls the same method the code under test is
    responsible for calling cannot see that call go missing. `composed` above
    starts `application.media_proposals` as a side effect of `start()` --
    every projection is started by that one line, by design -- so a suite
    built entirely on that fixture would never notice `media_proposals.start()`
    being deleted from `Application.start()`: the fixture would just... also
    not start it, and every assertion made through `application.media_proposals`
    below would raise `RuntimeError("the media-proposal projection has not
    been started")`, which looks like a fixture bug, not a wiring regression.

    This test builds the application and calls `curate()` without ever
    calling `application.start()` at all, so it fails on the `RuntimeError`
    from `MediaProposalRunner._started()` if `Application.start()` stops
    calling `self.media_proposals.start()` -- a failure this test's own setup
    cannot mask, because its setup never called `start()` either.
    """
    # `model=` a fake rather than the default `None`: `build_application`'s own
    # docstring says an omitted model builds a real `ChatOpenAI` against
    # `config.base_url()` -- construction alone touches no network, but there
    # is no reason for this file to depend on that being true when nothing
    # here exercises the agent's model at all.
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=db_path
    )
    project_id = uuid4()
    topic_id = uuid4()

    service = MediaCurationService(
        text=FakeCurationText([NEEDS_REPLY, TERMS_REPLY, JUDGEMENTS_REPLY]),
        search=FakeCurationSearch(),
        proposals=application.media_proposal_repository,
        topics=FakeCurationTopics(topic_id, _topic_detail(topic_id)),
    )
    await service.curate(project_id, topic_id)

    with pytest.raises(RuntimeError, match="not been started"):
        await application.media_proposals.for_project(project_id)

    # Now start it the ordinary way, and the same aggregate write is visible --
    # proving the RuntimeError above was about *this* runner's own start
    # state, not a hole in `media_proposal_repository`'s writes.
    await application.start()
    await application.media_proposals.caught_up()
    (row,) = await application.media_proposals.for_project(project_id)
    assert row.reason == "clear and on topic"

    await application.close()
