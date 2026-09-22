"""Prompting and parser rules for the media curation pipeline.

Extracts needs, terms, and judge prompts and output parsers from media curation.
A stage returning nothing usable is a legitimate outcome, not an error.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from research_team.research.application.topic_read import TopicDetail

logger = logging.getLogger(__name__)

#: How much of an unreadable reply `_unreadable` logs. Enough to see whether
#: the model answered prose, wrapped its JSON in something `_fenced` does not
#: strip, or emitted a reasoning preamble -- and short enough that a stage
#: failing on every need does not fill the log with the same 8KB reply.
UNREADABLE_LOG_CHARS = 500

MAX_NEEDS_PER_TOPIC = 4
"""Stage 1's cap on how many things a topic is allowed to want seen or heard.

A guess: no measurement yet says how many genuine needs a real topic states,
and four is chosen as "more than one, few enough that a person reviewing
proposals is not reviewing a report." It is a constant rather than a computed
limit because being wrong about it is visible (proposals run thin, or a person
scrolls past a wall of them) and cheap to fix, one number in one place, rather
than the alternative of no cap and an unbounded stage 1 reply setting the size
of every stage after it.
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

MAX_CANDIDATES_PER_NEED = 5
"""Stage 3's cap on how many judged results survive per need.

Combined with the two caps above, the worst case for one chain invocation is
`MAX_NEEDS_PER_TOPIC * MAX_QUERIES_PER_NEED` = 8 searches, and
`MAX_NEEDS_PER_TOPIC * MAX_CANDIDATES_PER_NEED` = 20 candidates proposed. Both
are guesses at where a review pane stops being reviewable and starts being a
chore, made constants for the reason every bound in this module is a
constant: a wrong guess is a number to change, not a redesign.

(This said 24 while the value was 3, which is 12. The arithmetic was wrong,
not the constant -- noted because the number was quotable and nobody
recomputed it.)

**Raised from 3 to 5 on 2026-08-16, and unlike the caps above this one is
measured.** With `_judge_prompt` asking for partial matches, the judge became
the looser constraint and this became the binding one: against the same
ten-result pool, `gemma-4-26b-qat` and `muse-glimmer-30b` both saturated it,
and muse marked `keep: true` on 8 of 10 -- rejecting only a blasting video
and something about a cat and a drawstring. Holding at 3 would have discarded
five candidates the judge wanted, which defeats the point of loosening it:
the product composes an answer from several sources ("this part of X, that
part of Y"), so the cap has to leave room for several.

Five rather than eight because a reviewer's attention is the scarce thing,
not the judge's willingness, and 8/10 was one need on one pool -- too thin to
set a bound on. If review starts feeling thin rather than long, this is the
number to raise.
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

    `None` means "this reply is not shaped like items at all", and is
    distinct from `[]`, which means "it is, and there are none". Every
    parser below keeps that distinction: `None` costs a `rejected_parses`
    and a logged reply, `[]` costs neither.

    This docstring used to say the opposite -- that the two were treated
    identically because "a stage that produced nothing usable is retried by
    running the chain again, the same as a stage whose reply did not parse."
    That reasoning is about the *remedy* and was used to justify collapsing
    the *report*, which does not follow. Two causes can share a fix and still
    need telling apart, and this very module argues that position twice
    elsewhere: `CurationUnavailable` refuses to fold a transport failure into
    an empty outcome, and `parse_judgements` separates "the judge said no"
    from "the item was junk" precisely so strictness cannot masquerade as
    malformation in the one number a caller reads.
    """
    try:
        payload = json.loads(_fenced(raw))
    except (ValueError, TypeError):
        return None
    items = _as_list(payload)
    if items is None:
        return None
    return [item for item in items if isinstance(item, dict)]


def _unreadable(stage: str, raw: str) -> None:
    """Log a reply no parser could read, with the reply itself in the record.

    **The reply is the evidence, and nothing else recovers it.** Every stage
    here answers an unreadable reply the same way it answers a genuinely
    empty one -- an empty list -- so by the time a count reaches a caller the
    text that caused it is gone. CLAUDE.md's extraction notes are the
    precedent: three minutes of logging what the model actually returned beat
    two hours of reasoning about what the code downstream does with the
    answer, and the defect there (`temporal_expression` filed under
    `properties`) was invisible from every direction until someone looked at
    the payload.

    WARNING rather than ERROR: the chain continues and the run is still
    valid. A stage that could not be read is a fact about one model call, not
    a failure of the request.
    """
    logger.warning(
        "media curation: %s reply was not readable as JSON items; got: %s",
        stage,
        raw[:UNREADABLE_LOG_CHARS],
    )


def parse_needs(text: str, *, need_id_prefix: str = "need") -> tuple[list[MediaNeed], int]:
    """Stage 1's reply, as the needs the document supports and a count of
    what was dropped.

    An item is dropped, and counted, if `medium`, `description` or `why` is
    missing or blank -- all three are what a person reviewing a need reads,
    and a need with a blank reason is not reviewable.

    Prose instead of JSON, or a JSON reply with no array in it, yields
    `([], 1)` and a WARNING carrying the reply -- **not `([], 0)`, which is
    what this returned until it cost an afternoon.** A topic that genuinely
    wants no imagery and a reply nobody could read are remedied the same way
    (run the chain again), and that was the stated reason for reporting them
    identically. It does not follow: sharing a remedy is not being the same
    event, and the count is the only place the difference could have shown.
    Measured on 2026-08-16 -- a woodworking topic returned two good needs and
    zero candidates, with `rejected_parses` reading 0, and no evidence
    existed anywhere to say whether stage 2 had answered prose or the judge
    had genuinely kept nothing. The list stays empty either way, so no
    caller's control flow changes; only the count stops lying.

    `need_id`s are assigned here, from position, because nothing upstream of
    this parser has offered one: the model is not asked for an id, and the
    order needs are listed appears to be the least arbitrary numbering
    available before the caller records them as events.
    """
    items = _items(text)
    if items is None:
        _unreadable("stage 1 (needs)", text)
        return [], 1
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
    if items is None:
        _unreadable("stage 2 (terms)", text)
        return [], 1
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
    if items is None:
        _unreadable("stage 3 (judgements)", text)
        return [], 1
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


def _needs_prompt(topic: TopicDetail) -> str:
    """Stage 1's prompt: the topic's own content, not its id.

    A need is a judgement about *this* topic's material -- what it asked,
    what it has found, what a diagram or photo would add that its prose
    findings don't. A prompt built from a bare identifier carries none of
    that, so the only needs it could produce are generic ones the model
    invents rather than ones the topic actually supports -- indistinguishable,
    by eye, from every other topic's stage 1 reply. `question`, `scope` and
    `findings` are the fields `TopicDetail` carries for exactly this: see
    "Stage 1" in the design doc.

    Sub-questions are included, each marked answered or open. Stage 1 is
    asked to find what would be *better seen than read*, and a sub-question
    already answered in prose is a signal that its ground is covered --
    without them, the model could not tell "still open" from "answered
    already", and might propose media for something the topic has already
    settled.
    """
    findings = "\n".join(f"- {f}" for f in topic.findings) or "(none yet)"
    sub_questions = (
        "\n".join(
            f"- [{'answered' if sq.resolved else 'open'}] {sq.question}"
            for sq in topic.sub_questions
        )
        or "(none)"
    )
    return (
        "What about this topic would be better seen or heard than read?\n"
        f"Question: {topic.view.summary.question}\n"
        f"Scope: {topic.scope}\n"
        f"Sub-questions:\n{sub_questions}\n"
        f"Findings so far:\n{findings}\n"
        'Answer with JSON: [{"medium": ..., "description": ..., "why": ...}]. '
        "If nothing here would, answer []."
    )


def _terms_prompt(need: MediaNeed) -> str:
    """Stage 2's prompt: one need, its own call, per the module docstring."""
    return (
        f"Need: {need.description}\nWhy: {need.why}\nMedium: {need.medium}\n"
        'Give search terms as JSON: [{"text": ..., "categories": "images"|"videos"}]. '
        "If none come to mind, answer []."
    )


def _judge_prompt(need: MediaNeed, results: list[SearchResult]) -> str:
    """Stage 3's prompt: the pool for one need, indexed by position.

    The index in each line is what `parse_judgements` reads back -- a judged
    item names a position in *this* listing, not any id of the result.

    **Partial matches are kept, and this is the load-bearing instruction.**
    Stage 1 writes compound needs -- "a slow-motion close-up of the pin being
    driven *and* a stress test comparing the joint against a glued one" -- and
    a judge reading that literally rejects every real video, because no single
    video is all of it. Measured on 2026-08-16 against one such need and ten
    genuinely on-topic drawboring videos: `gemma-4-26b-qat` and
    `muse-glimmer-30b` each kept **zero**, with correct reasons of the form
    "shows drawboring but does not include the stress test";
    `qwen3.8-27b-mtp` kept three only because it read the need loosely. Which
    model happened to be loaded decided whether the feature worked at all.

    The fix is to say what the product actually wants, which the old prompt
    never did: an answer is composed from several sources -- "this part of X,
    that part of Y" -- so a result covering one clause of a need is useful,
    not a failure to cover the rest. Rejection is reserved for off-topic.

    The cost is real and accepted: a looser judge proposes weaker candidates,
    and the person reviewing them absorbs that. `MAX_CANDIDATES_PER_NEED`
    bounds how many reach them, and rejecting a mediocre proposal is one
    click, where a need that silently kept nothing is invisible.
    """
    lines = [
        f"{i}. {r.title} -- {r.url} ({r.kind}): {r.snippet}" for i, r in enumerate(results)
    ]
    return (
        f"Need: {need.description}\nWhy: {need.why}\n"
        "Which of these results serve the need, in whole or in part? Judge "
        "only what is listed.\n"
        "A need is often satisfied by several results together rather than by "
        "one that covers all of it, so keep anything that covers part of the "
        "need -- one aspect, one step, one of several things asked for. "
        "Reject only what is off-topic or unusable.\n"
        + "\n".join(lines)
        + '\nAnswer with JSON: [{"index": ..., "keep": true|false, "reason": ...}].'
    )
