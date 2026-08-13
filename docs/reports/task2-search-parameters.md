# Task 2 — SearXNG `engines`, `categories`, `time_range`

Commit `9edc3bd` on `worktree-defects-and-decisions`.

## What changed

`research_team/infrastructure/agent/search.py`

- `build_search_tool(..., engines=None, categories=None, time_range=None)` —
  deployment defaults, aliased to `default_*` locals so the tool's own
  parameters can shadow them cleanly.
- `web_search(query, engines=None, categories=None, time_range=None)` — a call
  overrides the default per parameter; a parameter the call is silent about
  keeps its default rather than being cleared by a neighbour's override.
- Request params are built conditionally. An unset parameter is absent, never
  empty.
- Docstring the model reads says what each is *for* (`science`/`news`/`it`;
  when a recency bound is right and when it discards good sources; prefer
  `categories` over `engines` unless the instance is known).
- The memo key is built once from the **resolved** values and used for both
  `get` and `put`.
- `format_recalled` gained a paragraph on why it does *not* name the
  parameters, with the condition that would expire the argument.
- Corrected the stale "`attempts` … that is Task 6" claim (`composition.py:542`
  wires it).

`research_team/infrastructure/agent/recall.py`

- `query_key(request, *, engines=None, categories=None, time_range=None)`.
  Query normalization untouched; parameters appended as
  `\x1f<name>=<value>` for each set one, in fixed order.
- Values are compared **exactly** — no folding. Whether `Arxiv` == `arxiv` or
  `news,it` == `it,news` is a fact about one instance's configuration, and the
  module's rule is to fold only where the upstream is known insensitive.
- `\x1f` because `normalize_query` cannot emit it: Python counts it as
  whitespace, so `str.split` consumes it. A query cannot be crafted to collide
  with a parameterised entry.
- Unparameterised calls key byte-for-byte as before.

## Red, then green

The memo-collision test was proved red in two stages, deliberately. Run
against the untouched tool it fails on the *call log* (the tool silently drops
an unknown argument, so no restricted search is even attempted) — true but not
the defect. So the plumbing was landed first, with the key unchanged, which is
the exact state the bug lives in:

```
    await tool.ainvoke({"query": "backward design"})
    second = await tool.ainvoke({"query": "backward design", "time_range": "year"})

    # Asserted before the call log on purpose: the defect is the answer, not
    # the saved request, and this is the line that names it.
>   assert "result-all" not in second
E   AssertionError: assert 'result-all' not in '[recalled -...lt-all\nu\nc'
E
E     'result-all' is contained here:
E        search]
E
E       result-all
E       u
E       c

tests/infrastructure/test_search.py:416: AssertionError
```

That is the failure the task exists for: the year-bounded search never leaves
the process and is handed the unrestricted result set under a `[recalled …]`
header. It fails by returning the wrong answer, not by raising.

The full first red run, before any implementation, was **15 failed, 62
passed** across the two files — including `TypeError: query_key() got an
unexpected keyword argument 'time_range'` for every new recall test.

Green, after the key change:

```
tests/infrastructure/test_search.py .................................... [ 25%]
...                                                                      [ 27%]
tests/infrastructure/test_recall.py .................................... [ 52%]
..                                                                       [ 53%]
tests/infrastructure/test_page_memo.py ........                          [ 59%]
tests/infrastructure/test_fetch.py ..................................... [ 84%]
......................                                                   [100%]

============================= 144 passed in 1.12s ==============================
```

`tests/infrastructure/test_stage_middleware.py` also run (15 passed) since
Task 1's middleware shares the file. Full suite not run, per the plan.

## New tests

`tests/infrastructure/test_recall.py` — plain key is byte-for-byte unchanged;
each of the three parameters changes the key; each occupies its own named slot
(`engines=news` ≠ `categories=news`); two values of one parameter differ; the
query is still folded when parameters are present; the delimiter cannot be
forged from query text.

`tests/infrastructure/test_search.py` — the no-parameter request is exactly
`{"q", "format"}`; supplied parameters reach the instance; an instance default
applies and a call overrides it without clearing its neighbour; the
time_range/unrestricted memo collision (above); each parameter keeps its
search apart from the unrestricted one; a repeated *parameterised* search
still hits the memo once; a deployment default is part of the key a call is
stored under.

## Gates

- `uv run ruff check .` — All checks passed!
- `uv run ruff format --check .` — 211 files already formatted

Task 1's `_unwired` field left alone. `checks.py`, `fetch.py` untouched.
`docs/direction.md` left modified and unstaged.

## Where the plan was imprecise

1. **"The memo-collision test must fail by returning the wrong recalled
   answer — not by raising."** Written as though one run would show it. It
   cannot: with no parameter on the signature, langchain drops the unknown
   argument silently (it does not raise either), so the pre-implementation red
   is an ordinary assertion failure about a request that was never varied. The
   wrong-answer failure only exists once the parameter reaches the request and
   the key has not caught up. Landing the plumbing before the key was the only
   way to observe the stated failure; the report above shows both.

2. **The plan does not say what type the parameters take.** Implemented as
   `str | None` throughout, comma-separated for multi-valued ones, which is
   SearXNG's own wire format and keeps the model's job to writing one string.
   A `list[str]` would have needed a join and a decision about whether order
   folds in the key — a decision I would have had to make silently.

3. **Instance defaults and the key.** The plan says the parameters enter the
   key without saying whether a *default* does. It has to: the default reaches
   the instance, so two tools with different defaults would otherwise share
   entries in a shared `Recall`. Keyed on resolved values, with a test.
