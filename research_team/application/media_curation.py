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
where it was first defined, because `MediaCandidate` below carries one as a
field and the application layer may not import from infrastructure
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
from dataclasses import dataclass
from typing import Any, Literal, Protocol

MAX_NEEDS_PER_TOPIC = 4
"""Stage 1's cap on how many things a topic is allowed to want seen or heard.

A guess, the way `MAX_SEARCHES_PER_TURN` is a guess: no measurement yet says
how many genuine needs a real topic states, and four is chosen as "more than
one, few enough that a person reviewing proposals is not reviewing a report."
It is a constant, not a computed limit, for the same reason `MAX_SEARCHES_PER_TURN`
gives -- being wrong about it is visible (proposals run thin, or a person
scrolls past a wall of them) and cheap to fix, one number in one place, rather
than the alternative of no cap and an unbounded stage 1 reply setting the
size of every stage after it.
"""

MAX_QUERIES_PER_NEED = 2
"""Stage 2's cap on search terms generated for one need.

Per need rather than per topic on purpose (see the module docstring and the
design's "Stage 2" section): a bad query this way costs one need, not every
need in the topic. Two is a guess -- one query is often too literal a reading
of the need's description, and a third rarely finds something the first two
did not -- and it is a constant so the guess costs one number to revise, not
a re-read of every prompt that assumes it.
"""

MAX_CANDIDATES_PER_NEED = 3
"""Stage 3's cap on how many judged results survive per need.

Combined with the two caps above, the worst case for one chain invocation is
`MAX_NEEDS_PER_TOPIC * MAX_QUERIES_PER_NEED` = 8 searches, and
`MAX_NEEDS_PER_TOPIC * MAX_CANDIDATES_PER_NEED` = 24 candidates proposed. Both
are guesses at where a review pane stops being reviewable and starts being a
chore, made constants for the reason every bound in this module is a
constant: a wrong guess is a number to change, not a redesign.
"""


@dataclass(frozen=True)
class SearchResult:
    """One SearXNG result, flattened to the fields the media pipeline needs.

    `thumbnail_url` is the whole reason this type exists apart from the
    string `infrastructure.agent.search.format_results` renders: the review
    pane needs an image to show for a media result, and the model must never
    see that URL -- it costs context for something only a human-facing pane
    reads. Getting it by re-parsing `format_results`' prose would mean
    scraping a string built for a different reader; this is built once, by
    `infrastructure.agent.search.parse_results`, and rendered from in both
    directions.

    All fields are `str`, never `None` -- a field absent from a real payload
    becomes `""` at the point `parse_results` builds one of these, not a
    sentinel every caller here has to check for.
    """

    title: str
    url: str
    snippet: str
    kind: Literal["image", "video", "other"]
    asset_url: str
    detail: str
    thumbnail_url: str


@dataclass(frozen=True)
class MediaNeed:
    """One thing stage 1 decided would be better seen or heard than read.

    Recorded before anything is searched -- see the design's "Stage 1" section
    for why that is the one structural decision in the chain. `need_id` is
    assigned by the caller building the recorded event, not here: this type is
    the parser's output, and an id minted before verification would be an id
    for something that might not survive it.
    """

    need_id: str
    medium: str
    description: str
    why: str


@dataclass(frozen=True)
class Query:
    """One stage-2 search term for one need, and the SearXNG category to run
    it in.

    Per need rather than per topic, mirroring `MediaNeed`: a query that drifts
    off-topic costs the one need it was generated for, not the whole chain.
    """

    need_id: str
    text: str
    categories: str


@dataclass(frozen=True)
class Judgement:
    """Stage 3's verdict on one pooled candidate: kept, with the reason.

    `index` names a position in the per-need result pool the judge was shown,
    not an id of anything durable -- the pool exists only for the one call
    that judges it. `parse_judgements` returns only the *kept* verdicts: a
    `keep: false` item is the judge doing its job, not junk, so it is dropped
    silently rather than counted as a rejection -- see `parse_judgements` for
    the distinction between that and a genuinely malformed item.
    """

    need_id: str
    index: int
    reason: str


@dataclass(frozen=True)
class MediaCandidate:
    """One surviving proposal: the need it answers, the result, and why.

    The `reason` is the judge's one-line answer to "why does this serve the
    need" and is what the review pane shows beside the thumbnail -- see the
    design's "Stage 3" section. Assembling one of these from a `Judgement` and
    the result pool it indexes is the chain's job, not this module's; nothing
    here constructs a `MediaCandidate` yet.
    """

    need_id: str
    result: SearchResult
    reason: str


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


def _fenced(raw: str) -> str:
    """Strip a fenced code block, if the reply has one.

    Shared by all three parsers below because all three ask the same
    question of the model and get the same two answers back: JSON, or JSON
    wrapped in ``` fences despite being asked not to be. Identical to the
    unwrapping `parse_ontology` does, pulled out once rather than repeated
    three times.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text


def _as_list(payload: Any) -> list[Any] | None:
    """A list, whether the JSON handed over *is* one or merely *carries* one.

    Every stage here is prompted to answer with a bare JSON array. But models
    wrap lists in a keyed object routinely regardless of what was asked for,
    and `ontology_discovery.py` asks for exactly that shape
    (`{"classes": [...]}`) -- so a reader moving between the two files, or a
    model that has seen both prompts, will reach for the keyed form on
    instinct. A parser that reads only a bare array turns a perfectly good
    `{"needs": [...]}` reply into "no needs", and that is invisible: an empty
    result is *already* a legitimate outcome in this chain (see the module
    docstring), so there is nothing about the parser's output that tells a
    caller the data was there and it looked in the wrong place. This is the
    same class of failure CLAUDE.md's extraction notes describe for
    `temporal_expression` landing in `properties` -- nothing raises, the
    reply parses "successfully," and the count is just quietly short.

    So: a bare list is returned as-is. A dict with exactly one key whose
    value is a list returns that list -- not "the first list found in any
    key," which would silently pick a wrong field on a reply carrying more
    than one. Anything else, including a dict with zero or several list-typed
    keys, returns `None`. This would pass with a change reverted to "only
    accept a bare array" if no test fed it the keyed form -- the keyed-form
    tests in `test_media_curation.py` are what pin this.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        list_values = [value for value in payload.values() if isinstance(value, list)]
        if len(list_values) == 1:
            return list_values[0]
    return None


def _items(raw: str) -> list[dict[str, Any]] | None:
    """The reply's items, as dicts, or `None` if the reply isn't shaped that
    way at all.

    Accepts a bare JSON array or a single-key object wrapping one -- see
    `_as_list` for why both have to work.

    `None` here is not surfaced to callers as a distinct case the way
    `parse_ontology` surfaces it -- every parser below treats "not JSON" and
    "an empty array" identically, because unlike ontology discovery there is
    nothing here that needs to distinguish "examined, found none" from
    "unreadable, retry": a stage that produced nothing usable is retried by
    running the chain again, the same as a stage whose reply did not parse.
    """
    try:
        payload = json.loads(_fenced(raw))
    except (ValueError, TypeError):
        return None
    items = _as_list(payload)
    if items is None:
        return None
    return [item for item in items if isinstance(item, dict)]


def parse_needs(text: str, *, need_id_prefix: str = "need") -> tuple[list[MediaNeed], int]:
    """Stage 1's reply, as the needs the document supports and a count of
    what was dropped.

    An item is dropped, and counted, if `medium`, `description` or `why` is
    missing or blank -- all three are what a person reviewing a need reads,
    and a need with a blank reason is not reviewable. Prose instead of JSON,
    or a JSON reply with no `needs` array, yields `([], 0)`: a topic that
    wants no imagery and a reply nobody could read are both retried the same
    way (run the chain again), so this parser does not distinguish them --
    see `_items`.

    `need_id`s are assigned here, from position, because nothing upstream of
    this parser has offered one: the model is not asked for an id, and the
    order needs are listed appears to be the least arbitrary numbering
    available before the caller records them as events.
    """
    items = _items(text)
    rejected = 0
    needs: list[MediaNeed] = []
    for item in items or []:
        medium = item.get("medium")
        description = item.get("description")
        why = item.get("why")
        if (
            not isinstance(medium, str)
            or not medium.strip()
            or not isinstance(description, str)
            or not description.strip()
            or not isinstance(why, str)
            or not why.strip()
        ):
            rejected += 1
            continue
        needs.append(
            MediaNeed(
                need_id=f"{need_id_prefix}-{len(needs)}",
                medium=medium.strip(),
                description=description.strip(),
                why=why.strip(),
            )
        )
        if len(needs) == MAX_NEEDS_PER_TOPIC:
            break
    return needs, rejected


def parse_terms(text: str, *, need_id: str = "") -> tuple[list[Query], int]:
    """Stage 2's reply, as the queries one need's terms support.

    `need_id` is threaded through from the caller rather than parsed out of
    the reply: stage 2 is one call *per need* (see the module docstring), so
    the need a batch of queries belongs to is known before the call is made,
    not something the model states about itself.

    An item is dropped, and counted, if `text` is missing or blank.
    `categories` missing or blank is not a rejection -- it defaults to
    `"general"`, SearXNG's own default, because a query the model considered
    worth proposing should not be lost over the one field it is least likely
    to get wrong.
    """
    items = _items(text)
    rejected = 0
    queries: list[Query] = []
    for item in items or []:
        term = item.get("text")
        if not isinstance(term, str) or not term.strip():
            rejected += 1
            continue
        categories = item.get("categories")
        chosen = (
            categories.strip()
            if isinstance(categories, str) and categories.strip()
            else "general"
        )
        queries.append(Query(need_id=need_id, text=term.strip(), categories=chosen))
        if len(queries) == MAX_QUERIES_PER_NEED:
            break
    return queries, rejected


def parse_judgements(text: str, *, need_id: str = "") -> tuple[list[Judgement], int]:
    """Stage 3's reply, as the kept verdicts for one need's pooled results.

    `need_id` is threaded through the same way `parse_terms` threads it --
    stage 3 is one call per need's pool, not per topic.

    Two things are dropped here and they are not the same kind of dropped.
    An item missing `index` or `reason`, or whose `index` is not an `int`, is
    **rejected and counted**: it cannot be matched back to a result in the
    pool, which is what a citation-shaped verdict is for. An item with
    `keep: false` is **dropped and not counted**: the judge looked at that
    candidate and said no, which is the stage doing its job, not junk --
    counting it as a rejection would make "the judge was strict" look
    identical to "the judge's reply was malformed" in the one number a caller
    has to decide whether to worry about.
    """
    items = _items(text)
    rejected = 0
    kept: list[Judgement] = []
    for item in items or []:
        index = item.get("index")
        reason = item.get("reason")
        if not isinstance(index, int) or not isinstance(reason, str) or not reason.strip():
            rejected += 1
            continue
        if item.get("keep") is not True:
            continue
        kept.append(Judgement(need_id=need_id, index=index, reason=reason.strip()))
        if len(kept) == MAX_CANDIDATES_PER_NEED:
            break
    return kept, rejected
