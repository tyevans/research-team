"""Deciding what imagery or video would serve a topic, deterministically.

The chain asks the question the model would not think to ask on its own:
*what about this topic is better seen or heard than read?* It is a fixed
sequence of three small calls, not an agent loop -- each stage has one job,
one prompt, and a test. This module holds the ports the chain is built on and
the parser for each stage's reply.

**A stage returning nothing usable is a legitimate outcome, not an error.** A
topic can genuinely want no imagery, a need can genuinely suggest no
searchable term, and a judge can genuinely keep none of what a search
returned. A parser that raised on any of those would make the chain fail
exactly where it is supposed to say "nothing here" -- so every parser below
tolerates a reply that is not the asked-for shape, prose instead of JSON, or
an item missing a field, by dropping what cannot be trusted and counting it
rather than raising. This mirrors `_members` in `ontology_discovery.py`.

`SearchResult` lives here rather than in `infrastructure/agent/search.py`,
where it was first defined, because `MediaSearchPort` below returns it and
the application layer may not import from infrastructure
(`tests/test_architecture.py` enforces the direction). The type itself is
inert data with no framework and no I/O in it, so it moves to the layer that
needs it as a real type rather than infrastructure keeping it and application
re-declaring a structural lookalike Protocol for it -- a duplicate shape two
call sites have to keep in sync is worse than one import pointed the right
way. What stays in `infrastructure/agent/search.py` is `parse_results` and
everything under it: turning a SearXNG payload into this type is exactly the
job of adapting to a foreign system, which belongs in infrastructure, and
`search.py` now imports `SearchResult` from here instead of defining it.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.research.application.media_curation_prompts import (
    MAX_CANDIDATES_PER_NEED as MAX_CANDIDATES_PER_NEED,
)
from research_team.research.application.media_curation_prompts import (
    MAX_NEEDS_PER_TOPIC as MAX_NEEDS_PER_TOPIC,
)
from research_team.research.application.media_curation_prompts import (
    MAX_QUERIES_PER_NEED as MAX_QUERIES_PER_NEED,
)
from research_team.research.application.media_curation_prompts import (
    UNREADABLE_LOG_CHARS as UNREADABLE_LOG_CHARS,
)
from research_team.research.application.media_curation_prompts import (
    Judgement as Judgement,
)
from research_team.research.application.media_curation_prompts import (
    MediaNeed as MediaNeed,
)
from research_team.research.application.media_curation_prompts import (
    Query as Query,
)
from research_team.research.application.media_curation_prompts import (
    SearchResult as SearchResult,
)
from research_team.research.application.media_curation_prompts import (
    _as_list as _as_list,
)
from research_team.research.application.media_curation_prompts import (
    _fenced as _fenced,
)
from research_team.research.application.media_curation_prompts import (
    _items as _items,
)
from research_team.research.application.media_curation_prompts import (
    _judge_prompt as _judge_prompt,
)
from research_team.research.application.media_curation_prompts import (
    _needs_prompt as _needs_prompt,
)
from research_team.research.application.media_curation_prompts import (
    _terms_prompt as _terms_prompt,
)
from research_team.research.application.media_curation_prompts import (
    _unreadable as _unreadable,
)
from research_team.research.application.media_curation_prompts import (
    parse_judgements as parse_judgements,
)
from research_team.research.application.media_curation_prompts import (
    parse_needs as parse_needs,
)
from research_team.research.application.media_curation_prompts import (
    parse_terms as parse_terms,
)
from research_team.research.application.topic_read import TopicReadPort
from research_team.research.domain.media_proposals import (
    IdentifyMediaNeeds,
    MediaProposals,
    ProposeMedia,
)
from research_team.research.domain.urls import extract_hostname, normalize_url

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_CANDIDATES_PER_NEED",
    "MAX_NEEDS_PER_TOPIC",
    "MAX_QUERIES_PER_NEED",
    "UNREADABLE_LOG_CHARS",
    "CurationOutcome",
    "CurationUnavailable",
    "Judgement",
    "MediaCurationService",
    "MediaCurationTextPort",
    "MediaJudgePort",
    "MediaNeed",
    "MediaSearchPort",
    "Query",
    "SearchResult",
    "parse_judgements",
    "parse_needs",
    "parse_terms",
]


class MediaCurationTextPort(Protocol):
    """Turning a prompt into text, with the name of whatever did it.

    Mirrors `OntologyTextPort` in `ontology_discovery.py` exactly, and for the
    identical reason stated there: one method and one property is deliberately
    narrower than LangChain's `with_structured_output`, which appears nowhere
    in this repository. Anything wider would put LangChain's vocabulary in
    this layer's contract, which is what `tests/test_architecture.py` exists
    to prevent, and would make the fake in this module's test suite a mock of
    a chat model rather than six lines. Parsing happens here, in the
    application layer, tolerating junk the way `_members` does.
    """

    @property
    def model_name(self) -> str: ...

    async def generate(self, prompt: str) -> str: ...


class MediaSearchPort(Protocol):
    """Running one search and getting structured results back, no model
    involved.

    `categories` is passed through to SearXNG rather than typed as a closed
    set here -- the categories worth running against (`images`, `videos`)
    are a stage-2 prompting concern, not a constraint this port should
    enforce twice.
    """

    async def search(self, query: str, categories: str) -> tuple[SearchResult, ...]: ...


class MediaJudgePort(Protocol):
    """Evaluates pooled candidate search results against a stated media need."""

    async def judge_candidates(
        self, need: MediaNeed, candidates: Sequence[SearchResult]
    ) -> list[Judgement]: ...


def _host_of(url: str) -> str:
    """The comparison key for `ignored_hosts`, matching `domain/media_proposals.py`.

    Delegates to `extract_hostname` so invalid or malformed URLs are safely handled.
    """
    return extract_hostname(url)


class CurationUnavailable(Exception):
    """A port `MediaCurationService.curate` depends on failed to answer.

    Raised from `curate` when `self._text.generate` or `self._search.search`
    raises anything at all -- an unreachable SearXNG instance or an
    unreachable model endpoint are the two most likely operational failures
    of this feature, and previously neither was caught: the exception
    propagated straight out of `curate`, through `run_media_curation`, past
    the route's only `except CommandRejectedError`, and surfaced as an
    unhandled 500 with a stack trace in the log and no detail in the
    response.

    **Deliberately reported, not swallowed into an empty outcome.** Treating
    a transport failure as "zero needs, zero candidates" would be
    indistinguishable from a topic that genuinely has nothing worth
    proposing -- exactly the false-negative shape CLAUDE.md's extraction
    notes warn about ("nothing raises, the reply parses successfully, the
    count is just quietly short"). A person re-running the chain deserves to
    know the run never actually happened, not a plausible-looking zero. The
    route maps this to 502/503 rather than 500 so the response at least says
    which side of the boundary failed, instead of looking like an
    unrelated bug in this codebase.

    The original exception is chained (`raise ... from error`) so the cause
    is still in the log for whoever debugs the outage; only the *shape*
    reaching the route changes, from "opaque 500" to "named, reportable
    failure".
    """


@dataclass(frozen=True)
class CurationOutcome:
    """What one `curate` call did, as counts a caller can report or log.

    `ignored`, `rejected_parses` and `searched_empty` exist so a silent
    shortfall is never the only signal something happened -- "6 candidates, 2
    ignored" is a fact a person can act on; a bare "4 candidates" is not.

    `searched_empty` counts needs whose search pool came back with nothing at
    all, before judging. It is the one route to zero that no other field
    covers: a need can produce no terms, or terms that match nothing, and
    both leave `candidates`, `ignored` and `rejected_parses` all reading
    zero while the chain quietly `continue`s past stage 3. Separating it from
    `rejected_parses` is what distinguishes "the model gave us nothing to
    search for" from "the search found nothing" from "the reply was
    unreadable" -- three different things to go fix, previously one number.

    `judged_out` counts needs whose pooled candidates the judge saw and kept
    none of. It is the fifth route and the last silent one: a `keep: false`
    verdict is deliberately not a `rejected_parse` (see `parse_judgements`),
    so a judge that rejects everything leaves every other field at zero. That
    is the shape of the report this whole set of counts was added for.
    """

    needs: int
    candidates: int
    ignored: int
    rejected_parses: int
    searched_empty: int
    judged_out: int


class MediaCurationService:
    """Runs the three-stage chain for one topic and turns survivors into
    `MediaProposed` events.

    Takes an `AggregateRepository[MediaProposals]` rather than a narrower
    read/append port pair: the ignore filter below reads `ignored_assets` and
    `ignored_hosts` from the aggregate's own state, and this service has to
    load the aggregate anyway in order to append proposals to it. A
    constructor or method parameter carrying the ignored sets would be a
    second source of truth for what is ignored, alongside the one `decide`
    already enforces -- the two could disagree, and disagreeing is worse than
    either being wrong alone.
    """

    def __init__(
        self,
        *,
        text: MediaCurationTextPort,
        search: MediaSearchPort,
        proposals: AggregateRepository[MediaProposals],
        topics: TopicReadPort,
        judge: MediaJudgePort | None = None,
    ) -> None:
        self._text = text
        self._search_port = search
        self._proposals = proposals
        self._topics = topics
        self._judge = judge

    async def _generate(self, prompt: str) -> str:
        """`self._text.generate`, with a transport failure named rather than
        left to propagate as whatever exception the port's own
        implementation happens to raise -- see `CurationUnavailable`.
        """
        try:
            return await self._text.generate(prompt)
        except Exception as error:
            raise CurationUnavailable(
                f"the curation model failed to answer: {error}"
            ) from error

    async def _search(self, query: str, categories: str) -> tuple[SearchResult, ...]:
        """`self._search.search`, mirroring `_generate`'s wrapping."""
        try:
            return await self._search_port.search(query, categories)
        except Exception as error:
            raise CurationUnavailable(f"search failed: {error}") from error

    async def curate(self, project_id: UUID, topic_id: UUID) -> CurationOutcome:
        # A topic nobody has opened (a stale link, a wrong id) has nothing
        # for stage 1 to read -- answered the same way `TopicReadPort.read_topic`
        # answers it, `None`, rather than running a chain against an empty
        # prompt and calling that "examined". Nothing is loaded or appended:
        # there is no aggregate write worth making for a topic this project
        # doesn't have.
        topic = await self._topics.read_topic(topic_id)
        if topic is None:
            return CurationOutcome(
                needs=0,
                candidates=0,
                ignored=0,
                rejected_parses=0,
                searched_empty=0,
                judged_out=0,
            )

        aggregate = await self._proposals.load_or_create(project_id)

        needs, rejected = parse_needs(await self._generate(_needs_prompt(topic)))
        aggregate.execute(
            IdentifyMediaNeeds(
                project_id=str(project_id),
                topic_id=str(topic_id),
                needs=json.dumps(
                    [
                        {
                            "need_id": need.need_id,
                            "medium": need.medium,
                            "description": need.description,
                            "why": need.why,
                        }
                        for need in needs
                    ]
                ),
                model_version=self._text.model_name,
            )
        )
        # Saved before any search runs -- the one structural cost the chain
        # pays, and what it buys: a need survives a search that returns
        # nothing, is re-searchable later without re-running stage 1, and is
        # what a review pane groups proposals under. See the design's "Stage
        # 1" section and the module docstring above `MediaNeed`.
        await self._proposals.save(aggregate)

        candidates = 0
        ignored = 0
        searched_empty = 0
        judged_out = 0

        for need in needs:
            terms, terms_rejected = parse_terms(
                await self._generate(_terms_prompt(need)), need_id=need.need_id
            )
            rejected += terms_rejected

            pool: list[tuple[SearchResult, str]] = []
            for query in terms:
                for result in await self._search(query.text, query.categories):
                    pool.append((result, query.text))

            # Counted before the ignore filter, so the two cannot be confused:
            # an empty pool means nothing was found (or no terms were produced
            # to find it with), where a pool emptied by the filter is already
            # reported as `ignored`.
            if not pool:
                searched_empty += 1

            # The ignore filter runs here: after search, before stage 3. Not
            # at proposal time, which would pay a model call judging
            # candidates already excluded; not at search time, which SearXNG
            # cannot express (it has no notion of this project's ignore
            # list). Running it between the two is also what makes the count
            # reportable -- the outcome says "N candidates, M ignored" rather
            # than silently returning fewer.
            kept: list[tuple[SearchResult, str]] = []
            for result, query_text in pool:
                asset_ignored = (
                    normalize_url(result.asset_url) in aggregate.state.ignored_assets
                )
                host_ignored = _host_of(result.asset_url) in aggregate.state.ignored_hosts
                if asset_ignored or host_ignored:
                    ignored += 1
                    continue
                kept.append((result, query_text))

            if not kept:
                continue

            if self._judge is not None:
                judgements = await self._judge.judge_candidates(need, [r for r, _ in kept])
            else:
                judgements, judge_rejected = parse_judgements(
                    await self._generate(_judge_prompt(need, [r for r, _ in kept])),
                    need_id=need.need_id,
                )
                rejected += judge_rejected

            # The fifth route to zero, and the one that reproduces the
            # original report exactly: the judge was shown real candidates,
            # answered with well-formed JSON, and kept none of them. Nothing
            # is wrong -- being strict is stage 3's job -- but it is a wholly
            # different fact from "nothing was found" or "the reply was
            # unreadable", and without this it reported identically to both.
            # Measured on 2026-08-16 against gemma-4-26b-qat: ten video
            # results, ten reasoned `keep: false` verdicts, and an outcome
            # whose every count read zero.
            if not judgements:
                judged_out += 1

            for judgement in judgements:
                if not 0 <= judgement.index < len(kept):
                    # The judge was shown exactly `len(kept)` results and
                    # answers by position in that listing; an index outside
                    # it points at nothing shown and is dropped the way every
                    # parser here drops what it cannot trust, rather than
                    # raising or guessing which candidate was meant.
                    continue
                result, query_text = kept[judgement.index]
                aggregate.execute(
                    ProposeMedia(
                        project_id=str(project_id),
                        proposal_id=str(uuid4()),
                        need_id=need.need_id,
                        topic_id=str(topic_id),
                        page_url=result.url,
                        asset_url=result.asset_url,
                        thumbnail_url=result.thumbnail_url,
                        kind=result.kind,
                        title=result.title,
                        reason=judgement.reason,
                        query=query_text,
                    )
                )
                candidates += 1

        if candidates:
            await self._proposals.save(aggregate)

        return CurationOutcome(
            needs=len(needs),
            candidates=candidates,
            ignored=ignored,
            rejected_parses=rejected,
            searched_empty=searched_empty,
            judged_out=judged_out,
        )
