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

import httpx
from langchain_core.tools import BaseTool, tool

from research_team.application import SEARCH_TOOL
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

MAX_SEARCHES_PER_TURN = 3
"""Searches of any kind this turn before `web_search` stops asking.

A budget, where `MAX_EMPTY_SEARCHES` is a streak, and the two bound different
failures. The streak catches a question the web cannot answer: three empties
and there is nothing there. This catches the opposite and more expensive case,
which is what it was added for -- a topic where every search *returns*
something, none of it settles the question, and the model keeps rephrasing.
Nothing in the streak counter fires on that, because any result at all resets
it, so before this a productive-but-inconclusive topic could search without
limit.

Three because a round is one topic (`research_round.py`'s "You are working one
topic in an autonomous research round", and `TopicRoundRunner` runs one round
as one turn), so a per-turn budget is a per-topic budget, and two or three
angles on one question is where looking harder stops paying. An interactive
turn is one user message, where the same number is tighter but still more than
most questions need.

It is deliberately not a floor: like the streak it changes what the tool
*returns*, and the model may respond by recording a gap, by answering from
what it already has, or by ignoring the notice and calling something else.
"""


@dataclass
class _Counter:
    """One turn's search counts: the empty streak, and the total spend.

    A class and not two `int`s on purpose -- see `SearchAttempts`.
    """

    empty: int = 0
    total: int = 0


class SearchAttempts:
    """One turn's search counts: the empty streak, and the total spend.

    Two bounds over one counter, because they catch different failures and
    neither subsumes the other. `exhausted()` is a streak -- three consecutive
    `"No results."` and the web does not have it. `budget_spent()` is a total
    -- three searches of any outcome and this turn has looked enough. A topic
    where every search returns something inconclusive trips only the second;
    a question nothing indexes trips only the first, and sooner.

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

    The budget counts all three, and the asymmetry is deliberate rather than
    an oversight. A turn whose instance is down should stop asking it: the
    streak's reasoning does not apply, since nothing is being claimed about
    what is out there, and three failed round trips is enough to establish
    that a fourth will fail too.

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
        """Any non-empty result clears this turn's streak.

        The *streak* only. `total` is a budget and survives a productive
        search -- clearing it here would make the budget unreachable on
        exactly the topic it exists for, where every search returns something
        and none of it settles the question.
        """
        self._current().empty = 0

    def record_search(self) -> int:
        """One more search this turn, of any outcome; returns the new total.

        Counted before the answer is known, and counted for a recalled answer
        too. Both follow from what the budget is for: the streak counter
        measures whether the web has an answer, and this one measures how long
        the model has been asking. A repeat query served from `Recall` costs no
        request, but it is the model going round again on a question it has
        already put -- which is the behaviour being bounded, not the traffic.
        """
        counter = self._current()
        counter.total += 1
        return counter.total

    def exhausted(self) -> bool:
        return self._current().empty >= MAX_EMPTY_SEARCHES

    def budget_spent(self) -> bool:
        return self._current().total >= MAX_SEARCHES_PER_TURN


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


def _media_line(result: dict) -> str | None:
    """The asset behind a media result, or None if this isn't one.

    Branching on `template` rather than on which keys are present, because
    presence does not imply a value: 20 of 262 captured image results carry
    `iframe_src` as an empty string and `length` as null. `template` was set on
    every one of the 353 media results captured, and is what SearXNG itself
    dispatches on.

    An asset with no URL takes no line at all. `image: ` with nothing after it
    would assert an asset exists, and a line that renders empty would put a
    blank line inside a block -- which the "\\n\\n" join reads as a separator.
    """
    template = _text(result, "template")
    if template == "images.html":
        asset, detail = _text(result, "img_src"), _text(result, "resolution")
        label = "image"
    elif template == "videos.html":
        asset, detail = _text(result, "iframe_src"), _text(result, "length")
        label = "video"
    else:
        return None
    if not asset:
        return None
    # `resolution` is passed through verbatim and deliberately not parsed:
    # engines disagree on its spelling within a single response -- "533 x 800"
    # from DuckDuckGo and "1060x1600" (U+00D7, no spaces) from Bing, measured
    # in the same capture. There is nothing to gain from normalizing a string
    # the model reads and nothing downstream computes on.
    return f"{label}: {asset}" + (f" ({detail})" if detail else "")


def format_results(payload: object, limit: int) -> str:
    """Flatten a SearXNG payload to title/url/snippet, capped at `limit`.

    A media result takes a fourth line naming the asset, because for images and
    videos `url` is the *page* the thing was found on and not the thing: an
    image search rendered with the three text lines is a list of gallery pages
    with every asset silently dropped, which is what this did before 2026-08-15.

    Total by construction: an instance is a foreign system, and `response.json()`
    only promises valid JSON, not a dict shaped the way SearXNG's docs say --
    a proxy error page rendered as JSON, or a future API change, can hand back
    a list, a string, or null just as easily. A missing key inside a well-formed
    payload is an ordinary thing for a search instance to send, not an exception
    for the agent to reason about; a payload that isn't a dict at all gets the
    same treatment, not a crash.
    """
    if not isinstance(payload, dict):
        return _MALFORMED_PAYLOAD
    results = payload.get("results") or []
    chosen = results[:limit]
    if not chosen:
        return "No results."
    blocks = []
    for result in chosen:
        # Every field is normalized to a non-empty placeholder: a blank line
        # inside a block, from an empty url or snippet, would read as a block
        # separator to anything counting on the "\n\n" join below.
        title = _text(result, "title") or "(untitled)"
        url = _text(result, "url") or "(no url)"
        snippet = " ".join(_text(result, "content").split()) or "(no snippet)"
        lines = [title, url, snippet]
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


def _budget_notice(count: int) -> str:
    """What `web_search` says instead of searching, past the turn's budget.

    Says "move on" in the two forms the model can act on, because the notice
    the streak sends -- `record_gap` and nothing else -- is the wrong advice
    here. Past the streak bound nothing was found; past this one, three
    searches' worth of results are already in the turn, and answering from
    them is usually the right move rather than declaring a gap.
    """
    return (
        f"web_search has been called {count} times this turn, which is the "
        "budget for one topic. Work with what those searches returned: record "
        "what they support, and if the question is still open, call "
        "`record_gap` saying what you tried and move on to the next topic. "
        "Another phrasing of the same question is not what is missing."
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

    @tool(SEARCH_TOOL)
    async def web_search(
        query: str,
        engines: str | None = None,
        categories: str | None = None,
        time_range: str | None = None,
    ) -> str:
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
            # by spending the round trip to confirm it.
            return _exhausted_notice(MAX_EMPTY_SEARCHES)
        if attempts is not None and attempts.budget_spent():
            # Checked before `Recall`, and so is the increment below: the
            # budget counts questions asked rather than requests made, and a
            # recalled answer is the model asking again. Checking after would
            # let a turn spin indefinitely on queries it has already put, which
            # is the shape this bounds.
            return _budget_notice(MAX_SEARCHES_PER_TURN)
        if attempts is not None:
            attempts.record_search()
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
                return format_recalled(remembered, query)
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
            return results
        except ValueError:
            # Not JSON. Overwhelmingly the default-settings case, and worth
            # naming precisely -- the model cannot fix it, but the person
            # reading the log can. Not counted: the instance never answered
            # the question, so this is not evidence of an absent result.
            return _JSON_DISABLED
        except httpx.HTTPError as error:
            # Unreachable, not empty -- an outage is not the model having
            # looked and found nothing, and must not be counted as if it were.
            return f"Could not reach the search instance: {error}"
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
