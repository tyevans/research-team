"""Web search, via a SearXNG instance.

The one tool in this system that leaves the process. It is registered only when
an instance is configured, and it is gated by the autonomy policy like the file
tools are -- both of which are what keep "nothing escapes" an accurate
statement about a default install rather than a fond memory.

Results are capped and flattened before they reach the model. An uncapped
result set is a context leak of exactly the kind the `elide` and `compact`
strategies exist to clean up afterwards, and it is cheaper not to make the mess.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from langchain_core.tools import BaseTool, tool

from research_team.application import SEARCH_TOOL
from research_team.application.media_curation import SearchResult
from research_team.application.tool_artifacts import Acknowledgement, Hit, HitList, SourceHits
from research_team.infrastructure.agent.recall import Recall, Recalled, describe_age, query_key

TIMEOUT = httpx.Timeout(10.0)

_JSON_DISABLED = (
    "The SearXNG instance did not return JSON. Its JSON API is disabled by "
    "default -- the instance needs `formats: [json]` under `search:` in its "
    "settings.yml. No results this time."
)

_MALFORMED_PAYLOAD = (
    "The SearXNG instance returned JSON that was not a results object -- a "
    "misconfigured instance or a proxy error page can do this. No results "
    "this time."
)

MAX_EMPTY_SEARCHES = 3
"""Consecutive `"No results."` answers before `web_search` stops asking.

Not a floor and not a gate -- see `SearchAttempts`. The number is a guess at
where "still worth trying a different phrasing" turns into "this is not
findable," and it is cheap to change if the guess is wrong; nothing else
depends on the exact value.
"""


@dataclass
class _Counter:
    """One turn's consecutive-empty streak.

    A class and not a bare `int` on purpose -- see `SearchAttempts`.
    """

    empty: int = 0


class SearchAttempts:
    """One turn's consecutive-empty search streak.

    One bound: `exhausted()` is a streak -- three consecutive `"No results."`
    and the web does not have it.

    There was a second bound here, a per-turn *total* (`MAX_SEARCHES_PER_TURN
    = 3`, `budget_spent()`), meant for a topic where every search returns
    something inconclusive and the model keeps rephrasing. It is gone as of
    2026-08-21, on the report that research agents were getting three searches
    for a whole run rather than three per turn. Whether the refresh was
    genuinely broken or the budget was simply too tight to tell the difference
    was not established -- and did not need to be, because a research round is
    exactly the workload the budget hurt most: three angles on one topic is
    not looking hard, it is the *opening*. The streak is what remains, and it
    bounds the failure that actually costs something (asking the web for what
    the web does not have) without bounding a productive search at all.

    Deliberately not a permission mechanism: it does not withhold `web_search`
    from the tool list the way `TOOL_FLOORS` withholds `fetch`, and nothing
    here touches the autonomy policy. It changes what the tool *returns* past
    the bound, which the model is free to act on or ignore -- the same shape
    `fetch`'s `UNREADABLE` notice uses for a page that will never render.

    Only `"No results."` counts *toward the streak*. An unreachable instance,
    a non-JSON payload, or a malformed one is not an absent answer -- it is
    search failing to happen at all, and counting it would tell the model to
    record a gap (a claim that the search was tried and nothing was there) it
    has no evidence for. `build_search_tool` enforces this by comparing the
    result string, not by catching exceptions here.

    The instance is process-wide -- `build_application` constructs one for the
    one `web_search` tool the whole process shares -- but the *count* is not:
    it lives in a `ContextVar` that `SearchAttemptsMiddleware.begin_turn`
    refreshes before each turn's first model call, so two turns running
    concurrently hold two counts. The tool and its SearXNG client are still
    built once; only the counter is per-turn, which is the whole of what needs
    to be. `test_two_concurrent_turns_do_not_bound_each_other` fails if that
    stops being true.

    **What the var holds is a mutable counter, never a bare `int`, and that is
    load-bearing.** A child task copies its parent's context at spawn: a value
    set before the spawn is visible in the child, but a `set()` performed
    inside the child is invisible to the parent and to siblings. Storing a
    mutable object means the tool mutates state the middleware installed and
    can still see, whether or not langgraph runs a tool call in the same task
    as `before_agent`. Simplifying this to an integer would leave every test
    passing and lose the count on any turn whose tool calls run in child tasks.
    """

    def __init__(self) -> None:
        # One counter shared by every context that never had one installed:
        # a tool built without the middleware around it -- a test, or any
        # caller wiring the tool alone -- stays unbounded-per-process rather
        # than raising, exactly as it behaved when the count lived on the
        # instance. It is a field rather than the var's default because ruff's
        # B039 rejects mutable ContextVar defaults, and rightly: a default is
        # evaluated once and shared, which here is the intent but is the bug
        # everywhere else.
        self._unwired = _Counter()
        # Per-instance rather than module-level so two applications in one
        # process do not share a count.
        self._counter: ContextVar[_Counter | None] = ContextVar(
            f"search_attempts_{id(self):x}", default=None
        )

    def _current(self) -> _Counter:
        installed = self._counter.get()
        return self._unwired if installed is None else installed

    def begin_turn(self) -> None:
        """Install a fresh count for this turn.

        Distinct from `reset()`: `reset()` clears whatever counter this context
        can already see, which is what a productive search wants. This replaces
        it, so a turn cannot clear a concurrent turn's streak.
        """
        self._counter.set(_Counter())

    def record_empty(self) -> int:
        """One more consecutive empty result this turn; returns the new count."""
        counter = self._current()
        counter.empty += 1
        return counter.empty

    def reset(self) -> None:
        """Any non-empty result clears this turn's streak."""
        self._current().empty = 0

    def exhausted(self) -> bool:
        return self._current().empty >= MAX_EMPTY_SEARCHES


_HIGHLIGHT = str.maketrans("", "", "")
"""SearXNG wraps every term matching the query in U+E000/U+E001 before it
serializes a result -- private-use codepoints its own templates turn into
`<span>`s and nothing else has any meaning for.

Measured 2026-08-15 against a real instance: present in 29 of 262 results for
one image query, 0 of 29 for a general one and 0 of 91 for a video one. So it
is engine-specific (duckduckgo images) rather than universal, which is why it
reached the model unnoticed for as long as it did -- most searches never see
it, and the ones that do render as an invisible glyph rather than as mojibake.
"""


def _text(result: dict, key: str) -> str:
    """One field as clean text, or "" if it isn't one.

    Separate from an inline `str(result.get(key, ""))` because that idiom
    defends against a *missing* key and not a present-and-null one, and a real
    instance sends both. Measured in the same capture: `publishedDate` was null
    in 262 of 262 image results, `img_format` in 35, `thumbnail` in 22 of 91
    videos, `iframe_src` in 1. `str(None)` is the four characters "None", which
    on the media line below would read to the model as an asset URL.
    """
    value = result.get(key)
    if not isinstance(value, str):
        # Not `str(value)`: a number would survive that, but so would None and
        # every dict a future API change might nest here. A field that isn't
        # text is a field this function has nothing to say about.
        return ""
    return value.translate(_HIGHLIGHT).strip()


def parse_results(payload: object, limit: int) -> tuple[SearchResult, ...] | None:
    """A SearXNG payload as structured data, capped at `limit`.

    Returns `None` for a payload that isn't a results object -- the same
    "total by construction" reasoning `format_results` used to carry directly:
    an instance is a foreign system, and `response.json()` only promises valid
    JSON, not the dict shape SearXNG's docs describe. `format_results` turns
    `None` into `_MALFORMED_PAYLOAD`; a caller consuming the data has to decide
    for itself what a malformed instance means for it, which is why this
    doesn't collapse the two cases into an empty tuple.
    """
    if not isinstance(payload, dict):
        return None
    results = payload.get("results") or []
    # The payload guard above is total for the payload's own shape, but
    # not one level down -- `{"results": ["oops"]}` is a well-formed payload
    # carrying a result that is not a dict, and `_parse_one`'s `result.get`
    # raised `AttributeError` on it. Skipped rather than raised, matching the
    # totality this function already promises for the payload itself: a
    # skipped result is still a result set, where a raised exception was a
    # lost turn.
    return tuple(_parse_one(result) for result in results[:limit] if isinstance(result, dict))


def _parse_one(result: dict) -> SearchResult:
    """One SearXNG result dict to `SearchResult`.

    Branches on `template` rather than on which keys are present, because
    presence does not imply a value: 20 of 262 captured image results carry
    `iframe_src` as an empty string and `length` as null. `template` was set on
    every one of the 353 media results captured, and is what SearXNG itself
    dispatches on.
    """
    title = _text(result, "title") or "(untitled)"
    url = _text(result, "url") or "(no url)"
    snippet = " ".join(_text(result, "content").split()) or "(no snippet)"
    template = _text(result, "template")
    kind: Literal["image", "video", "other"]
    if template == "images.html":
        kind, asset, detail = "image", _text(result, "img_src"), _text(result, "resolution")
    elif template == "videos.html":
        kind, asset, detail = "video", _text(result, "iframe_src"), _text(result, "length")
    else:
        kind, asset, detail = "other", "", ""
    # `thumbnail_src` was absent on 46 of 262 captured image results, and
    # `thumbnail` is frequently an empty string where it is present -- both
    # measured on the same capture as everything else in this file. The third
    # fallback is `img_src` specifically, not "this result's asset": for a
    # video, the asset is `iframe_src`, an embed URL rather than an image, and
    # landing that in an `<img src>` in the review pane renders broken.
    # `img_src` was present on 91 of 91 captured video results and carries the
    # poster frame, so it is a real fallback rather than a guess -- and for a
    # non-media result it is simply absent, so the chain ends at `""` there.
    thumbnail = (
        _text(result, "thumbnail_src")
        or _text(result, "thumbnail")
        or _text(result, "img_src")
    )
    return SearchResult(
        title=title,
        url=url,
        snippet=snippet,
        kind=kind,
        asset_url=asset,
        detail=detail,
        thumbnail_url=thumbnail,
    )


def _media_line(result: SearchResult) -> str | None:
    """The asset behind a media result, or None if this isn't one.

    An asset with no URL takes no line at all. `image: ` with nothing after it
    would assert an asset exists, and a line that renders empty would put a
    blank line inside a block -- which the "\\n\\n" join reads as a separator.
    """
    if result.kind == "other" or not result.asset_url:
        return None
    # `resolution` (and `length`) are passed through verbatim and deliberately
    # not parsed: engines disagree on their spelling within a single response
    # -- "533 x 800" from DuckDuckGo and "1060x1600" (U+00D7, no spaces) from
    # Bing, measured in the same capture. There is nothing to gain from
    # normalizing a string the model reads and nothing downstream computes on.
    parenthetical = f" ({result.detail})" if result.detail else ""
    return f"{result.kind}: {result.asset_url}" + parenthetical


def format_results(payload: object, limit: int) -> str:
    """Flatten a SearXNG payload to title/url/snippet, capped at `limit`.

    A media result takes a fourth line naming the asset, because for images and
    videos `url` is the *page* the thing was found on and not the thing: an
    image search rendered with the three text lines is a list of gallery pages
    with every asset silently dropped, which is what this did before 2026-08-15.

    A pure renderer over `parse_results` since 2026-08-16 -- the model-facing
    string and the pipeline's structured data are built from one parse rather
    than two, so a field either function reads can't drift out of step with
    what the other reports for the same result.
    """
    parsed = parse_results(payload, limit)
    if parsed is None:
        # `_MALFORMED_PAYLOAD` returned by identity, not rebuilt here:
        # `build_search_tool` compares it with `is not` to decide whether to
        # cache, and an equal-but-distinct string would silently start caching
        # error pages.
        return _MALFORMED_PAYLOAD
    if not parsed:
        return "No results."
    blocks = []
    for result in parsed:
        # Every field is normalized to a non-empty placeholder in `_parse_one`:
        # a blank line inside a block, from an empty url or snippet, would
        # read as a block separator to anything counting on the "\n\n" join
        # below.
        lines = [result.title, result.url, result.snippet]
        media = _media_line(result)
        if media is not None:
            lines.append(media)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_recalled(recalled: Recalled, query: str) -> str:
    """An earlier result set, labelled with when and for what.

    Names the query that produced the entry rather than the one just asked,
    because normalization means they need not be identical. A model that can
    see the difference can ask again; one that cannot would take results for a
    neighbouring question as answering its own.

    It deliberately does *not* name `engines`, `categories` or `time_range`,
    and that is not an omission. The query is reported because normalization
    can merge two spellings of it, so a hit does not imply the same text. The
    parameters are in the key unfolded, compared exactly, so a hit *does* imply
    they were identical -- there is nothing to disagree about and a line saying
    `time_range=year` would only restate the call the model just made. If the
    parameters ever gain folding of their own, that argument expires and this
    has to name them.
    """
    asked = "" if recalled.asked == query else f" for {recalled.asked!r}"
    return (
        f"[recalled -- searched{asked} {describe_age(recalled.age_seconds)} in this "
        f"process, not a fresh search]\n\n{recalled.text}"
    )


def hit_list_artifact(query: str, results: tuple[SearchResult, ...]) -> HitList:
    """The `HitList` a fresh, genuine result set hands the console.

    `web_search` maps onto `hit_list` beside `search_sources` -- see the
    design doc's shape table -- rather than the `entity_list` an earlier draft
    of the plan named for it, which does not fit: a web result carries no
    `entity_type` or `relationship_count`, only a title, a url and a snippet,
    which is the same shape `search_sources` already draws.

    One `SourceHits` per result, keyed on the result's url rather than a
    document id this corpus never assigned one -- a web result has no
    document to page through, so there is nothing for a second hit on the
    same source to add. `start`/`end` are `0`/`len(snippet)`, the only
    honest offsets for text with no underlying document to be a range of;
    `char_count` is `0` for the same reason, and the renderer's ruler is
    simply not drawn for a source with nothing to measure against.

    Only called on a genuine, freshly-fetched result set -- a recalled
    answer has no structured results behind it (`Recall` stores the
    formatted string, not the parse), so it is acknowledged instead of
    reconstructed from text that would have to be re-parsed to build this.
    """
    sources = tuple(
        SourceHits(
            source_id=result.url,
            title=result.title,
            label=None,
            char_count=0,
            total=1,
            hits=(Hit(start=0, end=len(result.snippet), snippet=result.snippet),),
        )
        for result in results
    )
    return HitList(pattern=query, total=len(results), suppressed=0, sources=sources)


def _exhausted_notice(count: int) -> str:
    """What `web_search` says instead of searching, past the bound.

    Names the count so the number in the notice always matches
    `MAX_EMPTY_SEARCHES` even if that constant changes, and names
    `record_gap` explicitly -- the tool the model should reach for is not
    something it should have to infer from "stop searching."
    """
    return (
        f"web_search has returned no results {count} times in a row this turn. "
        "Searching again is unlikely to find something the last "
        f"{count} attempts did not. If you looked and did not find it, call "
        "`record_gap` to say so rather than searching again."
    )


def build_search_tool(
    base_url: str,
    *,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
    recall: Recall | None = None,
    attempts: SearchAttempts | None = None,
    engines: str | None = None,
    categories: str | None = None,
    time_range: str | None = None,
) -> BaseTool:
    """A `web_search` tool against one SearXNG instance.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network. `recall` and `attempts` are optional so a
    caller that does not want either behaviour still gets a working tool.

    `engines`, `categories` and `time_range` set instance defaults for a
    deployment whose instance is configured for a particular kind of work; a
    call that names one overrides it for that call alone. They are the
    SearXNG parameters of the same names and are passed through unvalidated --
    the list of engines a given instance runs is that instance's business, and
    an unknown one is answered by the instance rather than guessed at here.
    """
    # Bound to differently-named locals because the tool's own parameters
    # shadow these: inside `web_search`, `engines` is what this call asked for
    # and `default_engines` is what the deployment configured.
    default_engines, default_categories = engines, categories
    default_time_range = time_range

    @tool(SEARCH_TOOL, response_format="content_and_artifact")
    async def web_search(
        query: str,
        engines: str | None = None,
        categories: str | None = None,
        time_range: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Search the web. Returns titles, URLs, and short snippets.

        `categories` narrows what kind of thing is searched -- `science` for
        papers and scholarly sources, `news` for reporting, `it` for technical
        documentation. Reach for it when the general web would bury what you
        want under the wrong kind of page.

        `time_range` bounds how recent a result may be: `day`, `week`, `month`
        or `year`. Use it when the answer has changed and an older page would
        be wrong rather than merely old -- a current version number, an ongoing
        situation. Leave it off for anything settled; it discards good sources
        that happen to be old.

        `engines` names specific SearXNG engines (comma-separated, e.g.
        `arxiv`, `wikipedia`) when you want one source rather than a
        consensus. Which engines exist depends on the instance, so prefer
        `categories` unless you know the instance runs the one you name.
        """
        query_engines = engines if engines is not None else default_engines
        query_categories = categories if categories is not None else default_categories
        query_time_range = time_range if time_range is not None else default_time_range
        # Unset parameters are absent from the request, never sent empty:
        # SearXNG reads an empty `time_range` and an absent one differently,
        # and `test_a_search_with_no_parameters_sends_exactly_what_it_always_sent`
        # fails if this becomes an unconditional dict with empty values.
        request_params = {"q": query, "format": "json"}
        if query_engines is not None:
            request_params["engines"] = query_engines
        if query_categories is not None:
            request_params["categories"] = query_categories
        if query_time_range is not None:
            request_params["time_range"] = query_time_range
        if attempts is not None and attempts.exhausted():
            # Past the bound, the request is never made -- the whole point is
            # that another search would not help, so there is nothing to gain
            # by spending the round trip to confirm it. A refusal, not a
            # result: `Acknowledgement(ok=False)` rather than an empty
            # `HitList`, so the console draws it as punctuation rather than as
            # a card claiming zero matches were found.
            text_out = _exhausted_notice(MAX_EMPTY_SEARCHES)
            return text_out, Acknowledgement(
                action=SEARCH_TOOL, subject=query, detail=text_out, ok=False
            ).as_artifact()
        # Keyed explicitly rather than through `Recall`'s default, which would
        # key on the bare normalized query and collide with `fetch`'s URL keys.
        # The parameters are part of it because the instance answers
        # differently for them; keyed on the query alone, a year-bounded search
        # is served the unrestricted search's results under a `[recalled]`
        # label. See `query_key`. The *resolved* values, not the call's, so a
        # deployment default is as much a part of the key as an argument is.
        memo_key = query_key(
            query,
            engines=query_engines,
            categories=query_categories,
            time_range=query_time_range,
        )
        if recall is not None:
            remembered = recall.get(query, key=memo_key)
            if remembered is not None:
                # A recalled answer has no structured results behind it --
                # `Recall` stores `format_results`' string, not the parse --
                # so there is nothing to build a `HitList` from without
                # re-parsing text that was formatted to be read, not to be
                # parsed back. Acknowledged instead: not an error, but not the
                # shape this tool draws when it actually has results either.
                text_out = format_recalled(remembered, query)
                return text_out, Acknowledgement(
                    action=SEARCH_TOOL, subject=query, detail="recalled"
                ).as_artifact()
        owned = client is None
        http = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            response = await http.get(
                f"{base_url}/search",
                params=request_params,
            )
            response.raise_for_status()
            payload = response.json()
            results = format_results(payload, limit)
            if attempts is not None:
                # Only the literal "No results." counts as an empty answer --
                # everything else that reaches this line (a genuine result
                # set, or the malformed-payload sentinel handled below) is not
                # evidence that nothing is out there.
                if results == "No results.":
                    attempts.record_empty()
                else:
                    attempts.reset()
            if recall is not None and results is not _MALFORMED_PAYLOAD:
                # Only a genuine result set is remembered -- and "No results."
                # counts as one; it's an answer, not a failure. A 200 with a
                # malformed body (a proxy error page serialized as JSON, say)
                # doesn't raise, so `format_results` returns this sentinel by
                # identity rather than a fresh string each time; caching it
                # would serve the same "not a results object" message back as
                # a *recalled* answer for up to an hour, and the retry that
                # would have succeeded never happens -- the same failure this
                # transport-error guard exists to prevent, reached by a path
                # that never raises.
                recall.put(query, results, key=memo_key)
            if results is _MALFORMED_PAYLOAD:
                return results, Acknowledgement(
                    action=SEARCH_TOOL, subject=query, detail=results, ok=False
                ).as_artifact()
            # Both "a genuine result set" and "No results." build a `HitList`
            # -- an empty one for the latter, `parse_results` returning `()`
            # -- the same convention `search_sources` uses for a valid search
            # that matched nothing: not found is an answer, not an error.
            parsed = parse_results(payload, limit) or ()
            return results, hit_list_artifact(query, parsed).as_artifact()
        except ValueError:
            # Not JSON. Overwhelmingly the default-settings case, and worth
            # naming precisely -- the model cannot fix it, but the person
            # reading the log can. Not counted: the instance never answered
            # the question, so this is not evidence of an absent result.
            return _JSON_DISABLED, Acknowledgement(
                action=SEARCH_TOOL, subject=query, detail=_JSON_DISABLED, ok=False
            ).as_artifact()
        except httpx.HTTPError as error:
            # Unreachable, not empty -- an outage is not the model having
            # looked and found nothing, and must not be counted as if it were.
            text_out = f"Could not reach the search instance: {error}"
            return text_out, Acknowledgement(
                action=SEARCH_TOOL, subject=query, detail=text_out, ok=False
            ).as_artifact()
        finally:
            if owned:
                await http.aclose()

    return web_search


SEARCH_PROMPT = (
    "\n\nYou can search the web with the `web_search` tool. What it returns is "
    "a snapshot at the moment you searched, recorded permanently in this "
    "session's log -- not a live view you can refresh by asking again. Asking "
    "the same question twice returns the first answer, marked as recalled and "
    "naming the query it came from; if that query is not the one you meant, "
    "ask a different one rather than the same one again. If a search is "
    "refused, that refusal is your answer for this turn.\n\n"
    "Search when your own knowledge is stale or thin for the question at "
    "hand, not reflexively on every question you could plausibly answer "
    "yourself -- each search is a real request against a real instance, not a "
    "free way to double-check."
)
