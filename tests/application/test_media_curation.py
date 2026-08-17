"""The three stage parsers, and the chain that drives them: tolerant of junk,
blind to nothing usable.

Mirrors `tests/application/test_ontology_discovery.py`'s treatment of
`_members_from` -- each parser is exercised for a dropped-and-counted item, a
prose reply that yields nothing, and the per-topic/per-need cap.

The service tests below use a real `MediaProposals` aggregate over a real
`AggregateRepository`, the way `test_corpus_editing.py` uses a real `Corpus`:
`decide`'s ignore guards are the aggregate's, not this service's, and a
hand-written fake state would have to reimplement them correctly to prove the
service reads what the aggregate actually holds rather than a copy of it.
"""

import json
from uuid import uuid4

import pytest
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.media_curation import (
    MAX_CANDIDATES_PER_NEED,
    MAX_NEEDS_PER_TOPIC,
    MAX_QUERIES_PER_NEED,
    CurationUnavailable,
    MediaCurationService,
    SearchResult,
    parse_judgements,
    parse_needs,
    parse_terms,
)
from research_team.application.topic_attention import TopicAttention
from research_team.application.topic_read import SubQuestionView, TopicDetail, TopicView
from research_team.application.topics import TopicSummary
from research_team.domain.media_proposals import (
    IgnoreMediaHost,
    MediaNeedsIdentified,
    MediaProposals,
    MediaProposed,
)


def _need(i: int) -> dict:
    return {"medium": "image", "description": f"need {i}", "why": "because"}


def _term(i: int) -> dict:
    return {"text": f"query {i}", "categories": "images"}


def _judgement(i: int) -> dict:
    return {"index": i, "keep": True, "reason": f"reason {i}"}


def test_parse_needs_drops_an_item_missing_its_description_and_counts_it():
    needs, rejected = parse_needs(
        json.dumps(
            [
                {"medium": "image", "description": "", "why": "x"},
                {"medium": "image", "description": "A map", "why": "y"},
            ]
        )
    )
    assert [n.description for n in needs] == ["A map"]
    assert rejected == 1


def test_parse_needs_returns_nothing_for_prose_instead_of_json():
    """A model that answers in prose is a legitimate outcome, not an error:
    a topic can genuinely want no imagery, and a parser that raised would
    make the chain fail where it should return nothing.

    This would still pass if `parse_needs` raised and the test caught the
    exception instead of asserting `== []` -- what pins the no-raise
    behaviour is that the call above is unguarded.

    The count is 1, not 0, and that changed on 2026-08-16: prose is a reply
    nobody could read, which is a different fact about the run from a model
    that read the topic and said "nothing here". Both still yield no needs,
    so no caller's control flow depends on which happened -- see
    `test_parse_needs_separates_an_unreadable_reply_from_an_empty_one`.
    """
    needs, rejected = parse_needs("I don't think this topic needs images.")
    assert needs == []
    assert rejected == 1


def test_parse_needs_separates_an_unreadable_reply_from_an_empty_one():
    """The distinction the three parsers exist to preserve, pinned once.

    An empty array is the model answering the question with "none"; prose is
    the model not answering it. Both produce no needs. Only the count tells
    them apart, and until 2026-08-16 it did not -- a real run reported two
    needs and zero candidates with `rejected_parses` at 0, and which stage
    had failed could not be recovered from the response at all.

    Fails if either parser branch is deleted: dropping the `items is None`
    guard makes prose report 0, and counting `[]` as a rejection makes the
    empty case report 1.
    """
    assert parse_needs("[]") == ([], 0)
    assert parse_needs("not json at all") == ([], 1)
    assert parse_terms("[]") == ([], 0)
    assert parse_terms("no terms come to mind") == ([], 1)
    assert parse_judgements("[]") == ([], 0)
    assert parse_judgements("none of these work") == ([], 1)


def test_parse_needs_honours_the_cap():
    needs, _ = parse_needs(json.dumps([_need(i) for i in range(10)]))
    assert len(needs) == MAX_NEEDS_PER_TOPIC


def test_parse_terms_drops_an_item_missing_its_text_and_counts_it():
    queries, rejected = parse_terms(
        json.dumps(
            [
                {"text": "", "categories": "images"},
                {"text": "roman forum ruins", "categories": "images"},
            ]
        )
    )
    assert [q.text for q in queries] == ["roman forum ruins"]
    assert rejected == 1


def test_parse_terms_returns_nothing_for_prose_instead_of_json():
    """Same legitimate-empty-outcome reasoning as `parse_needs`: a need can
    genuinely suggest no searchable term, and this must not raise for it.

    Counted as one unreadable reply -- see `parse_needs`' prose test."""
    queries, rejected = parse_terms("No good search terms come to mind.")
    assert queries == []
    assert rejected == 1


def test_parse_terms_honours_the_cap():
    queries, _ = parse_terms(json.dumps([_term(i) for i in range(10)]))
    assert len(queries) == MAX_QUERIES_PER_NEED


def test_parse_judgements_drops_an_item_missing_its_index_and_counts_it():
    judgements, rejected = parse_judgements(
        json.dumps(
            [
                {"keep": True, "reason": "no index"},
                {"index": 0, "keep": True, "reason": "the clearest of the three"},
            ]
        )
    )
    assert [j.reason for j in judgements] == ["the clearest of the three"]
    assert rejected == 1


def test_parse_judgements_returns_nothing_for_prose_instead_of_json():
    """A judge that keeps none of the pooled results is legitimate -- the
    search returned nothing worth proposing -- and must not raise.

    Counted as one unreadable reply -- see `parse_needs`' prose test. A judge
    that genuinely keeps nothing answers `[]` or a list of `keep: false`
    verdicts, neither of which is counted here."""
    judgements, rejected = parse_judgements("None of these results are usable.")
    assert judgements == []
    assert rejected == 1


def test_parse_judgements_drops_items_the_model_marked_keep_false():
    """A `keep: false` verdict is not malformed -- it is the judge doing its
    job -- so it must not be counted as a rejection the way a missing field
    is. This would pass if `parse_judgements` ignored `keep` entirely and
    returned every well-formed item; what it pins is that the survivors are
    exactly the kept ones."""
    judgements, rejected = parse_judgements(
        json.dumps(
            [
                {"index": 0, "keep": False, "reason": "duplicate of index 1"},
                {"index": 1, "keep": True, "reason": "clear and on topic"},
            ]
        )
    )
    assert [j.index for j in judgements] == [1]
    assert rejected == 0


def test_parse_judgements_honours_the_cap():
    judgements, _ = parse_judgements(json.dumps([_judgement(i) for i in range(10)]))
    assert len(judgements) == MAX_CANDIDATES_PER_NEED


def test_parse_needs_accepts_the_keyed_form_identically_to_the_bare_array():
    """Models wrap lists in a keyed object routinely, and `ontology_discovery.py`
    asks for exactly that shape -- a parser that only reads a bare array turns
    a perfectly good answer into "no needs", indistinguishable from the model
    genuinely declining. This would pass if `parse_needs` accepted only the
    bare-array form and this test fed it one; it feeds the keyed form instead,
    so it is red until the parser reads both."""
    bare = parse_needs(json.dumps([_need(0), _need(1)]))
    keyed = parse_needs(json.dumps({"needs": [_need(0), _need(1)]}))
    assert [n.description for n in keyed[0]] == [n.description for n in bare[0]]
    assert keyed[1] == bare[1]


def test_parse_terms_accepts_the_keyed_form_identically_to_the_bare_array():
    bare = parse_terms(json.dumps([_term(0), _term(1)]))
    keyed = parse_terms(json.dumps({"queries": [_term(0), _term(1)]}))
    assert [q.text for q in keyed[0]] == [q.text for q in bare[0]]
    assert keyed[1] == bare[1]


def test_parse_judgements_accepts_the_keyed_form_identically_to_the_bare_array():
    bare = parse_judgements(json.dumps([_judgement(0), _judgement(1)]))
    keyed = parse_judgements(json.dumps({"judgements": [_judgement(0), _judgement(1)]}))
    assert [j.index for j in keyed[0]] == [j.index for j in bare[0]]
    assert keyed[1] == bare[1]


# --- MediaCurationService -----------------------------------------------


def _needs_json(n: int) -> str:
    return json.dumps([_need(i) for i in range(n)])


def _terms_json(n: int) -> str:
    return json.dumps([_term(i) for i in range(n)])


def _judgements_json(n: int) -> str:
    return json.dumps([_judgement(i) for i in range(n)])


def _result(url: str) -> SearchResult:
    return SearchResult(
        title="a result",
        url=url,
        snippet="",
        kind="image",
        asset_url=url,
        detail="",
        thumbnail_url="",
    )


class FakeTextPort:
    """Six lines, per `MediaCurationTextPort`'s own reasoning: canned replies
    returned in call order, not a mock of a chat model. `prompts` records what
    each call was asked, so a test can inspect what stage 3 was shown without
    the service exposing anything for that purpose alone."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-text-model"

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._replies.pop(0)


class FakeSearchPort:
    """Returns the same canned results for every query -- nothing under test
    here depends on distinguishing one query's results from another's."""

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = tuple(results)

    async def search(self, query: str, categories: str) -> tuple[SearchResult, ...]:
        return self._results


def _topic_detail(topic_id, *, question: str = "what did Rome eat?") -> TopicDetail:
    """A `TopicDetail` with content stage 1's prompt can be checked against --
    a distinctive `question` a test can look for verbatim in what the fake
    text port received, the way `_result`'s url is what a prompt is checked
    for elsewhere in this module.
    """
    summary = TopicSummary(
        topic_id=topic_id,
        question=question,
        status="open",
        sources=1,
        findings=1,
        open_sub_questions=1,
    )
    attention = TopicAttention(topic_id=topic_id, findings=())
    return TopicDetail(
        view=TopicView(summary=summary, attention=attention),
        rationale="",
        scope="diet and food supply of the city of Rome",
        sub_questions=(SubQuestionView(key="q1", question="what grain?", answer=None),),
        source_ids=("s1",),
        findings=("the annona distributed grain",),
        contested=False,
    )


class FakeTopicPort:
    """`TopicReadPort` over one canned `TopicDetail`, or `None` for every id
    not explicitly given one -- mirrors the real port's contract that a
    topic nobody opened reads as absence, not an error."""

    def __init__(self, topics: dict) -> None:
        self._topics = topics

    async def list_topics(self) -> list[TopicView]:
        raise NotImplementedError("unused by MediaCurationService")

    async def read_topic(self, topic_id) -> TopicDetail | None:
        return self._topics.get(topic_id)


@pytest.fixture
def project_id():
    return uuid4()


@pytest.fixture
def topic_id():
    return uuid4()


@pytest.fixture
def harness() -> InMemoryTestHarness:
    return InMemoryTestHarness()


@pytest.fixture
def proposals_repo(harness) -> AggregateRepository[MediaProposals]:
    # `event_publisher=harness.event_bus` so `harness.published_events` can
    # answer "was a `MediaNeedsIdentified` ever written", without this test
    # module reaching into the event store's stream-id rendering to find out.
    return AggregateRepository(
        harness.event_store, MediaProposals, event_publisher=harness.event_bus
    )


def _service(text, search, proposals_repo, topics=None, topic_id=None) -> MediaCurationService:
    # A caller that doesn't care about stage 1's prompt content gets a topic
    # for free, keyed to whatever `topic_id` it passes to `curate` -- most
    # tests in this module are about the chain after stage 1, not about it.
    if topics is None:
        topics = FakeTopicPort({topic_id: _topic_detail(topic_id)} if topic_id else {})
    return MediaCurationService(
        text=text, search=search, proposals=proposals_repo, topics=topics
    )


async def test_an_ignored_asset_is_filtered_before_the_judging_call(
    project_id, topic_id, proposals_repo
):
    """Filtering after search and before stage 3 is what stops us paying a
    model call for candidates already excluded -- and what makes the count
    reportable. Fails if the filter moves to proposal time: the judge port
    would then see two candidates rather than one, i.e. two `https://`
    occurrences in the judge prompt instead of one.

    The ignored host comes from the aggregate's own state, not a constructor
    or method argument -- `IgnoreMediaHost` is executed against the same
    repository the service reads from, so this proves the service consults
    the aggregate it must load anyway to append, not a second source of
    truth for what is ignored.
    """
    aggregate = await proposals_repo.load_or_create(project_id)
    aggregate.execute(IgnoreMediaHost(project_id=str(project_id), host="bad.example"))
    await proposals_repo.save(aggregate)

    port = FakeTextPort([_needs_json(1), _terms_json(1), _judgements_json(1)])
    search = FakeSearchPort(
        [_result("https://bad.example/x.jpg"), _result("https://ok.example/y.jpg")]
    )

    service = _service(port, search, proposals_repo, topic_id=topic_id)
    outcome = await service.curate(project_id, topic_id)

    assert outcome.ignored == 1
    # One surviving candidate reached the judge -- one "https://" in its prompt.
    assert len(port.prompts[2].split("https://")) == 2


async def test_needs_are_recorded_even_when_every_search_returns_nothing(
    project_id, topic_id, proposals_repo, harness
):
    """The one structural cost in the chain, and the thing it buys: "we
    looked for a gradient diagram and found none" is a fact rather than a
    silence. Fails if needs are only written alongside proposals -- with no
    candidate ever proposed, there would be nothing to save and no
    `MediaNeedsIdentified` published.
    """
    port = FakeTextPort([_needs_json(2), _terms_json(1), _terms_json(1)])
    search = FakeSearchPort([])

    service = _service(port, search, proposals_repo, topic_id=topic_id)
    outcome = await service.curate(project_id, topic_id)

    assert outcome.needs == 2
    assert outcome.candidates == 0
    assert any(isinstance(e, MediaNeedsIdentified) for e in harness.published_events)
    # Both needs searched and found nothing, and the outcome says so. This is
    # the route to zero that no other count covers: with `searched_empty`
    # absent, this run and a run whose judge rejected everything report an
    # identical (0, 0, 0), which is what made a real zero undiagnosable on
    # 2026-08-16. Fails if the counter moves after the ignore filter, where
    # an empty pool would already have been skipped.
    assert outcome.searched_empty == 2
    assert (outcome.ignored, outcome.rejected_parses) == (0, 0)


async def test_stage_1_is_prompted_with_the_topics_own_content(
    project_id, topic_id, proposals_repo
):
    """Stage 1 has to see *this* topic's question, or it can only invent
    generic needs -- indistinguishable, by eye, from any other topic's reply.
    This asserts on the prompt the fake text port actually received, not
    merely that `curate` returned something: a return-value-only assertion
    would still pass with `TopicReadPort` unwired and the prompt built from
    the bare id, which is the bug this test exists to catch.
    """
    question = "what did the eruption of Vesuvius destroy?"
    topics = FakeTopicPort({topic_id: _topic_detail(topic_id, question=question)})
    port = FakeTextPort([_needs_json(0)])
    search = FakeSearchPort([])

    await _service(port, search, proposals_repo, topics=topics).curate(project_id, topic_id)

    assert question in port.prompts[0]


async def test_curate_does_nothing_for_a_topic_this_project_does_not_have(
    project_id, topic_id, proposals_repo, harness
):
    """`TopicReadPort.read_topic` answers `None` for a stale link or a
    hand-edited id, the same as it would for a real caller -- and there is
    nothing for stage 1 to read in that case. Fails if `curate` runs the
    chain anyway against an empty prompt: the text port would be called and
    `MediaNeedsIdentified` would be published for a topic that does not
    exist.
    """
    port = FakeTextPort([])
    search = FakeSearchPort([])
    topics = FakeTopicPort({})

    outcome = await _service(port, search, proposals_repo, topics=topics).curate(
        project_id, topic_id
    )

    assert (outcome.needs, outcome.candidates, outcome.ignored) == (0, 0, 0)
    assert port.prompts == []
    assert harness.published_events == []


async def test_a_proposed_event_carries_the_judges_reason_and_the_query_that_found_it(
    project_id, topic_id, proposals_repo, harness
):
    """Review test gap 7: no existing test pinned the index -> result mapping,
    or that `reason`/`query` on `MediaProposed` are the judge's actual reason
    and the query that produced the candidate, rather than something else
    threaded through by coincidence. `test_running_the_chain_answers_202_with_outcome_counts`
    (route level) and `test_an_ignored_asset_is_filtered_before_the_judging_call`
    (prompt-shape level) only check counts -- neither would catch
    `ProposeMedia(..., page_url=result.url, asset_url=result.asset_url, ...)`
    in `MediaCurationService.curate` being written with `result.url` swapped
    for `result.asset_url`, or `reason`/`query` swapped for each other.

    A distinctive result (`url` and `asset_url` deliberately different, unlike
    `_result`'s helper above) and a distinctive judge reason make that swap
    visible: this test is red if either field lands wrong.
    """
    port = FakeTextPort(
        [
            _needs_json(1),
            _terms_json(1),
            json.dumps([{"index": 0, "keep": True, "reason": "shows the aqueduct's arches"}]),
        ]
    )
    search = FakeSearchPort(
        [
            SearchResult(
                title="Pont du Gard",
                url="https://example.com/gallery/pont-du-gard",
                snippet="a Roman aqueduct bridge",
                kind="image",
                asset_url="https://cdn.example.com/pont-du-gard-full.jpg",
                detail="",
                thumbnail_url="https://cdn.example.com/pont-du-gard-thumb.jpg",
            )
        ]
    )

    service = _service(port, search, proposals_repo, topic_id=topic_id)
    outcome = await service.curate(project_id, topic_id)

    assert outcome.candidates == 1
    proposed = [e for e in harness.published_events if isinstance(e, MediaProposed)]
    assert len(proposed) == 1
    event = proposed[0]
    # `page_url` is the page a reader would cite -- `result.url` -- not the
    # CDN asset that happened to serve it, matching `MediaAcceptWorker`'s own
    # reasoning for the same split.
    assert event.page_url == "https://example.com/gallery/pont-du-gard"
    assert event.asset_url == "https://cdn.example.com/pont-du-gard-full.jpg"
    assert event.reason == "shows the aqueduct's arches"
    assert event.query == "query 0"


async def test_curate_reports_a_transport_failure_rather_than_letting_it_propagate_as_a_500(
    project_id, topic_id, proposals_repo
):
    """Review finding 5: `curate` caught nothing from its ports, so an
    unreachable model endpoint or SearXNG instance surfaced as an unhandled
    500. This is red against the reverted code, where the underlying
    `RuntimeError` propagates uncaught instead of being wrapped.
    """

    class BrokenTextPort:
        model_name = "fake-text-model"

        async def generate(self, prompt: str) -> str:
            raise RuntimeError("connection refused")

    search = FakeSearchPort([])

    with pytest.raises(CurationUnavailable):
        await _service(BrokenTextPort(), search, proposals_repo, topic_id=topic_id).curate(
            project_id, topic_id
        )
