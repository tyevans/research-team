# The `explorer` Component Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sixth resolved component, `explorer`, in which the *reader* re-runs the author's timeline query with different parameters, at a cost the widget is engineered to bound.

**Architecture:** A new `REGISTRY` entry (`resolved=True`, one required `over: timeline`
seam, a `vary` axis list, a required `prompt`) plus a new `ExplorerWidget` that reuses the
existing `TimelineRepository`, `queryKeys.timeline`, `resolvedWidgetQuery` and
`.cmp-timeline-box` verbatim. No server route, no DTO, no mapper and no container key is
added or changed — the whole feature is a registry entry, a domain reader, one widget, one
`RENDERERS` line, and CSS for the control row.

**Tech Stack:** Python 3 / PyYAML / FastAPI (registry + validation only); React 19 +
TanStack Query v5 + TypeScript (`exactOptionalPropertyTypes` on); vitest (jsdom) +
vitest browser mode (Chromium); Tailwind v4 with a hand-written `components.css`.

**Spec:** `docs/superpowers/specs/2026-08-17-explorer-component-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Four gates, and passing three is not passing.** `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`.
  The two ruff commands run over the **whole repository**, not the files you touched.
- **The fifth gate is invisible from `verify`.** `research_team/interfaces/web/static` is a
  committed build artefact and CI fails on drift. **Any task touching `frontend/src` ends
  with `cd frontend && npm run build` and a commit of the rebuilt
  `research_team/interfaces/web/static/assets/app.js` and `.../assets/index.css`.**
  `npm run verify` runs the build and never compares its output against the tree.
- **Never run two `vitest` processes at once.** Concurrent runs fail spuriously with a
  coverage temp-file error naming nothing about the real cause.
- **Browser tests are not in `verify` and not in CI.** Run `cd frontend && npm run test:browser`
  by hand in the one task that adds one.
- **Container keys are plural.** `graphs`, `timelines`, `documents`. `timelines.timeline(...)`
  is the call. A wrong key typechecks through the `as unknown as AppContainer` cast in the
  test harness and resolves to `undefined` at runtime — the symptom is a widget stuck in
  `isPending` forever, not a type error.
- **`--fg-muted` and `--bg-raised` are not tokens this build defines.** Use `--fg-dim` and
  `--bg-raise`. An undefined custom property sets nothing and looks exactly like a rule that
  worked. Grep `frontend/src/styles/tokens.css` for every token you name.
- **`ResolvedFrame` and the widgets emit typographic apostrophes (`’`).** A straight-quote
  regex in a test never matches. Match on a fragment without the apostrophe.
- **A render-helper option typed `projectId?: ProjectId` with a destructuring default is
  inert when passed `undefined`** — the default fires and restores the project, so the
  "no project" test silently exercises the ordinary path. Type it `ProjectId | null`, pass
  `null`, and spread with `{...(projectId ? { projectId } : {})}`.
- **`border-solid` beside one directional width draws three unwanted sides.** Pair `border: 0`
  with the directional width, always.
- **Do not add anything to `COMPONENTS_FOR`.** A resolved component cannot resolve in a course
  file (no project in scope), and `test_a_resolved_type_does_not_reach_the_build_prompt_by_existing`
  fails if `explorer` reaches any artifact type.

---

## Design decisions this plan locks in

Read these before Task 1; the tasks assume them.

**`over` is a warning, not an error.** Spec §3 asks for "a validation warning naming what is
supported"; spec §7's jsdom line asks that "an unknown `over` renders as prose". An error
would route the block to `BrokenComponent` and there would be no widget left to render prose.
So `over` is `Spec(text, required=True)` and the whole-body `warn` hook is what names
`timeline` as the only supported value.

**`vary` rejects an unknown axis** (spec §7 says "rejecting"), so that is a per-field
`Checker` producing errors. The two axes are exactly `entity_type` and `window`. `limit` is
deliberately not an axis: spec §5 says `limit` bounds the response and not the server's work,
so varying it lets a reader change the picture without changing what it cost — the one
control that would teach the wrong thing.

**Two queries, sharing one cache.** Spec §1 requires that one backing read give the widget
both its initial view and its full picker vocabulary; spec §7 requires that each control
change the query the repository is called with. Both hold with:

- the *display* query = the author's window with the reader's current parameters, entity type
  included;
- the *vocabulary* query = the same window with **no** `entityType`, mounted only when
  `entity_type` is in `vary`.

They are built from the same `queryKeys.timeline`, so when the author wrote no `entity_type`
the two keys are identical and TanStack Query issues **one** request. The cost when the author
did write one is two reads on mount, once per session, and that is written into the widget's
docstring rather than hidden.

**The window commits on release.** Drafts live in component state and are copied into the
committed window on `blur`. `<input type="date">` produces `YYYY-MM-DD`, which is what the
route parses — spec §4's "the control produces the format the route accepts rather than
accepting free text".

**Zero requests on revisit** comes free from `resolvedWidgetQuery`'s `staleTime: 5 * 60_000`
plus `refetchOnMount: false` and a key that carries every bound. It is free and it is still
the test that matters, because a later refactor that keys on the project alone or drops the
spread silently costs a double pass per interaction.

---

## File structure

| File | Responsibility |
| --- | --- |
| `research_team/application/components.py` | `string_subset` checker, `_explorer_over` warn hook, the `explorer` `REGISTRY` entry |
| `research_team/application/ask_components.py` | `explorer` joins `ASK_COMPONENT_TYPES` |
| `tests/application/test_components.py` | registry shape, `over`, `vary`, craft |
| `tests/application/test_resolved_components.py` | the `string_subset` checker |
| `tests/application/test_ask_components.py` | the type reaches the ask prompt |
| `tests/integration/test_resolved_widget_routes.py` | the unfiltered vocabulary read, on a project nothing opened |
| `frontend/src/domain/lesson/widgets.ts` | `ExplorerAxis`, `ExplorerSpec`, `readExplorerQuery`, `varies` |
| `frontend/src/domain/lesson/widgets.test.ts` | reader unit tests (existing file — appended to) |
| `frontend/src/presentation/lesson/ExplorerWidget.tsx` | the widget |
| `frontend/src/presentation/lesson/ExplorerWidget.cost.test.tsx` | the cost behaviour, alone in its file |
| `frontend/src/presentation/lesson/ExplorerWidget.test.tsx` | the rest of what jsdom can judge |
| `frontend/src/presentation/lesson/ExplorerWidget.browser.test.tsx` | measured height in a markdown flow |
| `frontend/src/styles/components.css` | `.cmp-explorer-*` |
| `frontend/src/presentation/lesson/LessonDocument.tsx` | `RENDERERS.explorer` |
| `frontend/src/presentation/lesson/LessonDocument.explorer.test.tsx` | the seam |

---

### Task 1: The registry entry, the two validators, and the ask prompt

**Files:**
- Modify: `research_team/application/components.py` (add `string_subset` after `string_list`
  at ~line 288; add `EXPLORER_AXES`, `EXPLORER_BACKING_READS` and `_explorer_over` after
  `_compare_collisions` at ~line 548; add the `"explorer"` entry to `REGISTRY` immediately
  after the `"timeline"` entry)
- Modify: `research_team/application/ask_components.py:24-33`
- Test: `tests/application/test_components.py`, `tests/application/test_resolved_components.py`,
  `tests/application/test_ask_components.py`, `tests/integration/test_resolved_widget_routes.py`

**Interfaces:**
- Consumes: `Spec`, `Checker`, `Note`, `text`, `_typename`, `integer_between`, `ComponentType`,
  `MAX_TIMELINE_BANDS` — all already in `components.py`.
- Produces:
  - `string_subset(*allowed: str) -> Checker` — a list of bare strings, each of which must be
    in `allowed`.
  - `EXPLORER_AXES: tuple[str, ...] = ("entity_type", "window")`
  - `EXPLORER_BACKING_READS: tuple[str, ...] = ("timeline",)`
  - `_explorer_over(data: dict[str, Any]) -> list[Note]`
  - `REGISTRY["explorer"]` with `resolved=True`, `warn=_explorer_over`, and fields
    `over` (required text), `vary` (required, `string_subset`), `prompt` (required text),
    `entity_type`, `from`, `to` (text), `limit` (`integer_between(1, MAX_TIMELINE_BANDS)`).
  - `ASK_COMPONENT_TYPES` gains `"explorer"` as its ninth entry.
  - **The wire body Task 2's reader parses:** `data` keys are exactly the field names above,
    `snake_case`, unprojected (a resolved type's learner projection is identity).

- [ ] **Step 1: Write the failing registry tests**

Append to `tests/application/test_components.py`, after
`test_a_timeline_limit_past_the_server_s_cap_is_an_authoring_error`:

````python
EXPLORER = """\
```component:explorer
id: fourth-century-explorer
over: timeline
entity_type: Person
from: "0300-01-01"
to: "0400-01-01"
vary: [entity_type, window]
prompt: |
  Narrow to Emperors and pull the window back.
```
"""


def test_an_explorer_carries_its_query_through_both_views():
    """Projection identity, as for every resolved type. Red against a build
    that gave `explorer` a `strip` -- the reader would be handed controls over
    a query with no bounds in it and would not be told."""
    document = parse_document(EXPLORER, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["over"] == "timeline"
    assert author["data"]["vary"] == ["entity_type", "window"]
    assert learner["resolved"] is True


def test_an_explorer_over_something_unsupported_warns_by_name_and_still_renders():
    """The `over:` seam's whole point, from the design's section 3.

    A warning and not an error, deliberately: an error routes the block to the
    error panel, and the reader is then told the *author* wrote something
    broken rather than that this build cannot read that corpus yet. The widget
    renders the refusal as prose naming what is supported, which is what every
    other failure in these widgets does -- and an error would leave no widget
    to say it.

    Red against `Spec(one_of("timeline"), required=True)`, which is the obvious
    implementation and produces an error.
    """
    source = (
        "```component:explorer\nid: e\nover: graph\n"
        "vary: [entity_type]\nprompt: Look around.\n```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert [str(note) for note in block.warnings] == [
        "over: only 'timeline' is supported today, got 'graph'"
    ]


def test_an_explorer_that_varies_an_axis_that_does_not_exist_is_an_error():
    """Rejected rather than warned, unlike `over`. An unknown `over` still
    names a coherent intent this build cannot serve; an unknown axis names a
    control the widget would simply not draw, and an author who wrote
    `vary: [topic]` and saw two controls would have no way to learn why."""
    source = (
        "```component:explorer\nid: e\nover: timeline\n"
        "vary: [entity_type, topic]\nprompt: Look around.\n```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "vary[1]: expected one of entity_type, window, got 'topic'"
    ]


def test_an_explorer_needs_an_over_an_axis_and_a_prompt():
    """All three are required and the reasons differ. Without `prompt` the
    reader is handed controls with no reason to touch them (design section 3);
    without `vary` nothing is varyable and the block is a `timeline` with worse
    dressing; without `over` there is no backing read to make.

    The order is the order `fields` declares them in, which is what
    `validation_report` walks.
    """
    source = "```component:explorer\nid: e\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "over: required field missing",
        "vary: required field missing",
        "prompt: required field missing",
    ]


def test_an_explorer_limit_past_the_server_s_cap_is_an_authoring_error():
    """The same bound `timeline` carries, for the same reason: the route 422s
    on it, and an authoring-time note is a failure the model can act on where a
    fetch-time one is a failure only the reader sees."""
    source = (
        f"```component:explorer\nid: e\nover: timeline\nvary: [window]\n"
        f"prompt: Look.\nlimit: {MAX_TIMELINE_BANDS + 1}\n```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        f"limit: expected a whole number from 1 to {MAX_TIMELINE_BANDS}, "
        f"got {MAX_TIMELINE_BANDS + 1}"
    ]


def test_explorer_craft_says_limit_does_not_make_the_read_cheaper():
    """The same measured claim `timeline`'s craft carries, and it matters more
    here: an explorer re-runs the read on every window commit, so an author who
    believes `limit` bounds the cost will write one and hand a reader a control
    they think is cheap. Red against craft notes that describe `limit` only as
    a way to keep the widget readable."""
    from research_team.application.components import REGISTRY

    craft = " ".join(REGISTRY["explorer"].craft).lower()

    assert "limit" in craft
    assert "cheaper" in craft or "less work" in craft


def test_explorer_craft_tells_the_author_a_reader_cannot_link_to_what_they_find():
    """Design section 5: no serialisable query state exists anywhere in this
    app, so a reader can explore and cannot share the result. The `prompt` the
    author writes is the only place expectations get set, and this is the only
    place the author will be told."""
    from research_team.application.components import REGISTRY

    craft = " ".join(REGISTRY["explorer"].craft).lower()

    assert "link" in craft or "share" in craft
````

Also widen the two parametrised lists in the same file. They are literals on purpose — adding
a type is meant to be a decision somebody made, not a derivation:

```python
@pytest.mark.parametrize(
    "name", ["definition", "evidence", "graph", "timeline", "compare", "explorer"]
)
def test_every_resolved_type_tells_the_model_how_to_write_a_good_one(name):
```

```python
def test_the_generated_reference_carries_every_resolved_example():
    reference = component_reference(
        only=["definition", "evidence", "graph", "timeline", "compare", "explorer"]
    )

    for name in ("definition", "evidence", "graph", "timeline", "compare", "explorer"):
        assert f"component:{name}" in reference
```

And in `tests/application/test_ask_components.py`, widen the existing set assertion inside
`test_every_resolved_type_is_offered_to_the_ask_agent`:

```python
    assert set(ASK_COMPONENT_TYPES) >= {
        "definition",
        "evidence",
        "graph",
        "timeline",
        "compare",
        "explorer",
    }
```

Leave `test_a_resolved_type_does_not_reach_the_build_prompt_by_existing` untouched: its
literal is the *unresolved* set, and it will now also prove that `explorer` stayed out of
`COMPONENTS_FOR`.

- [ ] **Step 2: Add the checker's own test**

Append to `tests/application/test_resolved_components.py`, beside
`test_string_list_checks_each_entry_by_its_own_path`, and add `string_subset` to that file's
existing import block from `research_team.application.components`:

```python
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["entity_type"], []),
        (["entity_type", "window"], []),
        ([], ["vary: expected at least 1 entry, got 0"]),
        ("window", ["vary: expected a list, got text"]),
        (["window", "topic"], ["vary[1]: expected one of entity_type, window, got 'topic'"]),
        ([{"axis": "window"}], ["vary[0]: expected text, got mapping"]),
    ],
)
def test_string_subset_names_the_allowed_values_at_the_offending_subscript(value, expected):
    """A list checker that reports `vary: bad axis` rather than `vary[1]` sends
    a model back to re-read a list it mostly got right. The path is the whole
    reason validation feedback is hand-written here -- see `components.py`'s
    module docstring.

    The mapping case is delegated to `text` rather than reported as "not one
    of": `{axis: window}` is a shape mistake and `topic` is a vocabulary
    mistake, and telling an author their mapping is not in a list of two
    strings is a diagnosis of the wrong problem.
    """
    check = string_subset("entity_type", "window")

    assert [str(note) for note in check(value, "vary")] == expected
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/application/test_components.py tests/application/test_resolved_components.py tests/application/test_ask_components.py -v`

Expected: FAIL. `KeyError: 'explorer'` on the registry tests, `ImportError: cannot import
name 'string_subset'` on the checker test, and an `AssertionError` on the widened set in
`test_every_resolved_type_is_offered_to_the_ask_agent`.

- [ ] **Step 4: Add `string_subset`, after `string_list` in `components.py`**

```python
def string_subset(*allowed: str) -> Checker:
    """A list of bare strings drawn from a closed vocabulary.

    `string_list` plus `one_of`, and neither alone will do: `string_list` has
    no vocabulary and `one_of` checks a scalar, so composing them by hand at
    the one call site would put the subscript arithmetic in a registry entry --
    which is where a path like `vary[1]` stops being maintained.

    Shape before vocabulary, deliberately. A mapping where a string belongs is
    reported by `text` as a mapping, not as "not one of entity_type, window":
    an author who wrote the wrong *kind* of thing is not helped by a list of
    the right values.
    """

    def check(value: Any, path: str) -> list[Note]:
        if not isinstance(value, list):
            return [Note(path, f"expected a list, got {_typename(value)}")]
        if not value:
            return [Note(path, "expected at least 1 entry, got 0")]
        notes: list[Note] = []
        for index, entry in enumerate(value):
            at = f"{path}[{index}]"
            shape = text(entry, at)
            if shape:
                notes.extend(shape)
            elif entry not in allowed:
                notes.append(Note(at, f"expected one of {', '.join(allowed)}, got {entry!r}"))
        return notes

    return check
```

- [ ] **Step 5: Add the two vocabularies and the warn hook, after `_compare_collisions`**

```python
EXPLORER_AXES: tuple[str, ...] = ("entity_type", "window")
"""Which parameters a reader may be given control of.

`limit` is deliberately absent and the omission is a ruling. `limit` bounds the
response and not the server's work -- it never reaches the store
(`graph_reader.py:294-299`) -- so a reader dragging it would change the picture
without changing what it cost, and would learn, wrongly, that the
cheap-looking control is the one that governs cost. Every axis here does
govern the answer honestly.

Named as a constant so the registry entry, the validator and the craft note
cannot come to list three different sets of axes.
"""

EXPLORER_BACKING_READS: tuple[str, ...] = ("timeline",)
"""What `over:` may name today.

A tuple with one entry, and that is the design's section 3 in a line: the field
exists so that a second backing read is a registry change rather than a new
component type. `GET /topics` and `GET /sources` take nothing worth varying,
and a graph explorer needs an entity-type vocabulary route this build does not
have -- so this stays at one until such a route exists.
"""


def _explorer_over(data: dict[str, Any]) -> list[Note]:
    """An unsupported `over:` is warned about, never rejected.

    The choice mirrors `_compare_collisions` and `_unknown_keys`: this is a
    "renders fine, does less than it says" defect, and refusing would cost the
    author the whole block plus the prose they wrote in `prompt`. The widget
    renders the refusal as a sentence naming what is supported, which is what
    every other failure in these widgets does -- and an error would route the
    block to the error panel where there is no widget left to say it.

    Runs only on a body that already validated, so `over` is present and is
    text (`ComponentType.warn`'s guarantee).
    """
    over = data.get("over")
    if over in EXPLORER_BACKING_READS:
        return []
    supported = ", ".join(repr(name) for name in EXPLORER_BACKING_READS)
    return [Note("over", f"only {supported} is supported today, got {over!r}")]
```

- [ ] **Step 6: Add the `REGISTRY` entry, immediately after the `"timeline"` entry**

````python
    "explorer": ComponentType(
        name="explorer",
        version=1,
        summary=(
            "A timeline the *reader* re-runs. The author fixes some "
            "parameters, names which ones the reader may change in `vary`, "
            "and writes a `prompt` inviting them to look."
        ),
        example=(
            "```component:explorer\n"
            "id: fourth-century-explorer\n"
            "over: timeline\n"
            "entity_type: Person\n"
            'from: "0300-01-01"\n'
            'to: "0400-01-01"\n'
            "vary: [entity_type, window]\n"
            "prompt: |\n"
            "  Narrow to Emperors and pull the window back to see how much of\n"
            "  the century the reigns actually cover.\n"
            "```"
        ),
        fields={
            # Required, and checked as plain text with the vocabulary enforced
            # by `warn` rather than by `one_of`. See `_explorer_over`: an
            # unsupported backing read has to reach the widget so the widget
            # can say so in prose.
            "over": Spec(text, required=True),
            "vary": Spec(string_subset(*EXPLORER_AXES), required=True),
            # Required, and the one field that makes an explorer worth more
            # than a timeline. Controls with no stated reason to touch them are
            # dressing, and a model left free to omit this will omit it.
            "prompt": Spec(text, required=True),
            # The same four the `timeline` entry takes, with the same
            # reasoning: quoted ISO instants bounding a half-open window,
            # either omittable for an open end, checked as text because the
            # route answers its own 422 naming which parameter was wrong and a
            # second date parser here would be a second thing to keep in step.
            "entity_type": Spec(text),
            "from": Spec(text),
            "to": Spec(text),
            "limit": Spec(integer_between(1, MAX_TIMELINE_BANDS)),
        },
        resolved=True,
        warn=_explorer_over,
        craft=(
            "Write this when you want the reader to look for something you did "
            "not name. If you are making a point with a particular window, "
            "write a `timeline` instead -- that is a view you chose, and this "
            "is an invitation to leave it.",
            "Quote the dates. An unquoted `from: 0300-01-01` is a YAML date, "
            "not a string, and YAML will not give you back the leading zero.",
            "`vary` is not a formality. Name only the axes you actually want "
            "moved: an author who set a window deliberately and one who did "
            "not are indistinguishable to a reader unless you say which.",
            "The `prompt` is the whole difference between this and a timeline. "
            "Say what you suspect is in there, not what the controls do -- a "
            "reader can see the controls.",
            "A reader cannot link to what they find. Nothing in this app puts "
            "filter state in the URL, so the only way to keep a view is a "
            "screenshot. Do not promise to share a result in your prompt.",
            "`limit` shortens what is drawn; it does not make the read "
            "cheaper. Measured, not assumed: the server walks the project's "
            "entities twice and applies the limit to the result, and the read "
            "is deliberately uncached. That bites harder here than in a "
            "`timeline`, because the reader re-runs it.",
        ),
    ),
````

- [ ] **Step 7: Add `explorer` to `ASK_COMPONENT_TYPES`**

In `research_team/application/ask_components.py`, add `"explorer"` after `"compare"` in the
tuple, and append these two paragraphs to the tuple's docstring — the existing character
measurement is now out of date, and saying so is cheaper and more honest than re-taking it:

```python
"""
`explorer` is the ninth and the first that is not a view but an invitation: the
reader re-runs the author's query rather than reading the one the author chose.
It belongs here for the same reason the other resolved types do -- an ask is
where a reader asks about the corpus -- and it is the type an ask suits best,
because an ask reader arrived with a question rather than with a curriculum.

The character measurement above was taken with eight types and has not been
re-taken. It is still the right order of magnitude and still the right warning:
this reference is paid on every ask turn.
"""
```

- [ ] **Step 8: Run the Python tests to verify they pass**

Run: `uv run pytest tests/application/test_components.py tests/application/test_resolved_components.py tests/application/test_ask_components.py -v`

Expected: PASS, including `test_the_prompt_an_ask_agent_receives_carries_every_offered_type`
— which is the wiring assertion for this half, because it reads `ASK_PROMPT` rather than the
tuple and would stay green if `component_reference(only=...)` had been hardcoded.

- [ ] **Step 9: Add the route test that starts from an unopened project**

Append to `tests/integration/test_resolved_widget_routes.py`:

```python
async def test_an_unfiltered_timeline_answers_for_a_project_nothing_has_opened(client):
    """The `explorer` widget's *vocabulary* read, which is a request no other
    widget makes: `/timeline` with no `entity_type` at all, so the response
    carries every type the picker can offer.

    Deliberately separate from `test_a_timeline_answers_for_a_project_nothing_
    has_opened` above rather than parametrised onto it. That test sends
    `entity_type=Person`, and CLAUDE.md's fixture trap is exactly the class of
    bug where the shape of a request decides whether a dependency is exercised
    -- collapsing the two would leave the unfiltered path with no test of its
    own starting from an untouched project.

    Red against a route that reached for a reader without opening the project:
    503 on the first request for every project and 200 on every one after,
    which reads as flakiness rather than as a bug.
    """
    project_id = await _untouched_project(client)

    response = await client.get(f"/api/projects/{project_id}/timeline")

    assert response.status_code == 200, response.text
    assert response.json()["bands"] == []
```

- [ ] **Step 10: Run it**

Run: `uv run pytest tests/integration/test_resolved_widget_routes.py -v`

Expected: PASS. Note in passing what this file's own docstring already says: these would pass
with the component reverted entirely. They cover the routes the widgets call, and they are
here because the widgets are the first callers to hit those routes on a project the console
has never displayed.

- [ ] **Step 11: Wiring — trace the type end to end**

Confirm by running, not by assuming. The precedent is CLAUDE.md's `EntityDefinitionRunner`,
never constructed in `composition.py`, serving empty cache misses while every test passed.

Write this to your scratchpad as `probe.py` and run it with `uv run python probe.py`:

```python
from research_team.application.ask_components import ASK_COMPONENT_TYPES, answer_document
from research_team.application.components import REGISTRY
from research_team.infrastructure.agent.ask_agent import ASK_PROMPT

assert REGISTRY["explorer"].resolved is True
assert "explorer" in ASK_COMPONENT_TYPES
assert "component:explorer" in ASK_PROMPT, "the model will never write one"

answer = (
    "```component:explorer\nid: e\nover: timeline\n"
    "vary: [entity_type, window]\nprompt: Look around.\n"
    'entity_type: Person\nfrom: "0300-01-01"\n```\n'
)
block = answer_document(answer)["blocks"][0]
print(block["type"], block["resolved"], block["withheld"], block["data"])
assert block["type"] == "explorer" and block["resolved"] is True
assert block["withheld"] == [] and block["data"]["vary"] == ["entity_type", "window"]
```

Expected: prints `explorer True []` and a `data` dict carrying `over`, `vary`, `prompt`,
`entity_type` and `from`. That is the exact shape Task 2's reader parses. **The remaining gap
is the client, and it is deliberate:** nothing in `RENDERERS` renders `explorer` yet, so the
block falls through to `UnknownComponent` and draws as a fence. Task 6 closes it.

- [ ] **Step 12: Gates**

Run, all three:
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

No frontend file changed in this task, so `npm run verify` and the rebuilt assets are not
required here.

- [ ] **Step 13: Commit**

```bash
git add research_team/application/components.py research_team/application/ask_components.py \
  tests/application/test_components.py tests/application/test_resolved_components.py \
  tests/application/test_ask_components.py tests/integration/test_resolved_widget_routes.py
git commit -m "Register \`explorer\`, the first component the reader re-runs

The sixth resolved type and the first where the reader chooses the query.
Registry-only in this commit: nothing renders it yet, so an \`explorer\` in an
answer draws as a fence until the widget lands.

\`over:\` is validated by \`warn\` rather than by \`one_of\`, and that is the one
decision here worth arguing. \`one_of\` is the obvious spelling and produces an
error, which routes the block to the error panel -- costing the author their
\`prompt\` prose and telling the reader the author wrote something broken, when
what actually happened is that this build cannot read that corpus yet. A
warning leaves the block renderable so the widget can say so in a sentence,
which is what every other failure in these widgets does.

\`vary\` goes the other way and rejects, because an unknown axis is a control
that simply would not be drawn -- an author who wrote \`vary: [topic]\` and saw
two controls has no way to learn why.

\`limit\` is not an offered axis. It bounds the response, not the server's work
(it never reaches the store), so a reader given that control would change the
picture without changing the cost, and would learn the wrong thing about which
of these knobs is expensive. The cost: an author who wants a shorter drawing
has to fix it themselves. Accepted.

Deliberately left undone: no graph explorer. It needs a route enumerating
entity types, which does not exist. \`over:\` is the seam it would arrive
through and EXPLORER_BACKING_READS is the one-line change it would be."
```

---

### Task 2: The domain reader

**Files:**
- Modify: `frontend/src/domain/lesson/widgets.ts` (append after `readTimelineQuery`, before
  the `readCompare` block or at the end — put it after `readTimelineQuery` so the two
  timeline-shaped readers sit together)
- Test: `frontend/src/domain/lesson/widgets.test.ts` — **this file already exists** and covers
  `readFlashcards`, `readMcq`, `readCloze`, `readChecklist`, `clozeBlanks` and `activeBlank`.
  Append to it; do not create it. It builds its blocks with a local `block()` helper that
  spreads a literal `ComponentBlock` rather than using `componentBlock` from the ask fixtures
  — reuse that local helper, so this module's tests keep one way of making a block.

**Interfaces:**
- Consumes: `ComponentBlock` (`./document.ts`), `TimelineWindow` and `readTimelineQuery`
  (same file), and the file-private `list`/`str` helpers already at the bottom of
  `widgets.ts`. The wire shape is Task 1's `data`.
- Produces, for Tasks 3–6:

```ts
export type ExplorerAxis = 'entity_type' | 'window'
export const EXPLORER_BACKING_READ = 'timeline'
export interface ExplorerSpec {
  readonly over: string
  readonly prompt: string
  readonly vary: readonly ExplorerAxis[]
  readonly window: TimelineWindow
}
export const readExplorerQuery: (block: ComponentBlock) => ExplorerSpec
export const varies: (spec: ExplorerSpec, axis: ExplorerAxis) => boolean
```

- [ ] **Step 1: Write the failing reader tests**

Append to the existing `frontend/src/domain/lesson/widgets.test.ts`. Add `readExplorerQuery`
and `varies` to its existing import from `./widgets.ts`, and reuse the `block()` helper
already at the top of that file (it spreads a literal `ComponentBlock` — `type: 'test'`,
`unknown: false`, `errors: []`, and the rest — which is all these readers need).

Then append:

```ts
/** What `readExplorerQuery` narrows out of an open record.
 *
 * The server's `data` is `Readonly<Record<string, unknown>>` because the set of
 * widget types is open, so every field here is a narrowing that must default
 * rather than throw -- a block that reached the browser malformed should draw
 * a degraded widget, not take the answer down.
 */

it('reads the author’s fixed window and the axes they opened', () => {
  const spec = readExplorerQuery(
    block({
      over: 'timeline',
      prompt: 'Narrow to Emperors.',
      vary: ['entity_type', 'window'],
      entity_type: 'Person',
      from: '0300-01-01',
      to: '0400-01-01',
      limit: 40,
    }),
  )

  expect(spec.over).toBe('timeline')
  expect(spec.prompt).toBe('Narrow to Emperors.')
  expect(spec.vary).toEqual(['entity_type', 'window'])
  expect(spec.window).toEqual({
    entityType: 'Person',
    from: '0300-01-01',
    to: '0400-01-01',
    limit: 40,
  })
})

it('drops an axis it does not implement rather than carrying it to a control', () => {
  // The registry rejects an unknown axis, so this shape only reaches here from
  // a hand-built block or from a *newer server* -- and the newer server is the
  // real case: an older bundle meeting `vary: [topic]` must draw the controls
  // it has, not crash or draw a dead third. Red against a reader that casts.
  const spec = readExplorerQuery(
    block({ over: 'timeline', prompt: 'Look.', vary: ['window', 'topic', 7] }),
  )

  expect(spec.vary).toEqual(['window'])
})

it('leaves every bound open when the author fixed none', () => {
  // An omitted bound is an open end, matching `readTimelineQuery`. Red against
  // a reader that defaults `from` to anything: the request would silently
  // narrow and the reader would explore a window nobody chose.
  const spec = readExplorerQuery(block({ over: 'timeline', prompt: 'Look.', vary: ['window'] }))

  expect(spec.window).toEqual({ entityType: null, from: null, to: null, limit: null })
})

it('reports an unsupported backing read as itself rather than defaulting it', () => {
  // `over` is warned about on the server and not rejected, so this body is
  // valid and reaches the widget. The widget renders prose naming what is
  // supported, and it can only do that if the reader passes the value through.
  // Red against `over: str(...) ?? 'timeline'`, which would silently run a
  // graph explorer's invitation against the timeline.
  const spec = readExplorerQuery(block({ over: 'graph', prompt: 'Look.', vary: ['window'] }))

  expect(spec.over).toBe('graph')
})

it('says an axis is closed when the author did not open it', () => {
  const spec = readExplorerQuery(block({ over: 'timeline', prompt: 'Look.', vary: ['window'] }))

  expect(varies(spec, 'window')).toBe(true)
  expect(varies(spec, 'entity_type')).toBe(false)
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/domain/lesson/widgets.test.ts`

Expected: FAIL — no such export `readExplorerQuery`. The existing tests in that file must
still pass; if they do not, you changed something you should not have.

- [ ] **Step 3: Add the reader to `widgets.ts`, after `readTimelineQuery`**

```ts
/** Which parameter a reader may move. Mirrors `EXPLORER_AXES` in
 *  `components.py`, and the duplication is the wire: the server validates the
 *  vocabulary and this narrows it, and neither can read the other. */
export type ExplorerAxis = 'entity_type' | 'window'

const EXPLORER_AXES: readonly ExplorerAxis[] = ['entity_type', 'window']

/** The only backing read this build serves. `over` is *not* defaulted to it:
 *  the server warns rather than rejects an unsupported value, so an
 *  `over: graph` body is valid and arrives here, and defaulting would run a
 *  graph explorer's invitation against the timeline without telling anyone. */
export const EXPLORER_BACKING_READ = 'timeline'

/** An `explorer` widget: the author's fixed query, and which parts of it the
 *  reader may move.
 *
 * `window` is a `TimelineWindow` and not a second shape, deliberately: the
 * backing read is `GET /timeline`, and a parallel type here would be another
 * thing to keep in step with `queryKeys.timeline` and `TimelineWindowQuery`
 * for no expressive gain. */
export interface ExplorerSpec {
  readonly over: string
  readonly prompt: string
  readonly vary: readonly ExplorerAxis[]
  readonly window: TimelineWindow
}

export const readExplorerQuery = (block: ComponentBlock): ExplorerSpec => ({
  over: str(block.data['over']) ?? '',
  prompt: str(block.data['prompt']) ?? '',
  // Filtered rather than cast. The registry rejects an unknown axis, so the
  // shape this guards against is a *newer server* sending an axis this build
  // does not implement -- and the right answer there is to draw the controls
  // we have, which is the same "an older reader does not call a newer document
  // broken" contract the unknown-fence path keeps.
  vary: list(block.data['vary']).filter((axis): axis is ExplorerAxis =>
    EXPLORER_AXES.includes(axis as ExplorerAxis),
  ),
  window: readTimelineQuery(block),
})

/** Whether the reader may move one axis. A function rather than a `Set` on the
 *  spec: `vary` is at most two entries, and a membership helper keeps the
 *  widget's JSX reading as prose. */
export const varies = (spec: ExplorerSpec, axis: ExplorerAxis): boolean =>
  spec.vary.includes(axis)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/domain/lesson/widgets.test.ts`

Expected: PASS — the five new tests plus every test that file already had.

- [ ] **Step 5: Wiring**

`readExplorerQuery` has no consumer yet — this is a leaf, and it is the one task in this plan
where "nothing reads it" is correct rather than a silo. Confirm the *upstream* half instead:

Run: `cd frontend && grep -n "over\|vary\|prompt\|entity_type" src/domain/lesson/widgets.ts`
and read it against Task 1's `REGISTRY["explorer"].fields`.

The keys must match exactly and must be `snake_case`. A `camelCase` slip here fails no test in
either language and produces a widget whose controls are all at their defaults.

- [ ] **Step 6: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 7: Commit, including the rebuilt assets**

```bash
git add frontend/src/domain/lesson/widgets.ts frontend/src/domain/lesson/widgets.test.ts \
  research_team/interfaces/web/static
git commit -m "Read an explorer's spec out of a block

\`vary\` is filtered against a known axis list rather than cast. The registry
already rejects an unknown axis, so the only body that reaches here with one is
from a server newer than this bundle -- and the contract there is the same one
the unknown-fence path keeps: an older reader draws what it can and does not
call a newer document broken.

\`over\` is deliberately not defaulted to 'timeline'. The server warns rather
than rejects an unsupported backing read, so the value arrives intact, and
defaulting would run a graph explorer's invitation against the timeline with
nothing anywhere saying so.

The rebuilt web/static assets are in this commit because CI compares them
against a fresh build and \`npm run verify\` does not."
```

---

### Task 3: The cost behaviour, and the widget that satisfies it

Written first, per spec §7: this is the requirement most likely to be quietly lost in a later
refactor, and it is the widget's main engineering content.

**Files:**
- Create: `frontend/src/presentation/lesson/ExplorerWidget.tsx`
- Create: `frontend/src/presentation/lesson/ExplorerWidget.cost.test.tsx`

**Interfaces:**
- Consumes: `readExplorerQuery`, `varies`, `EXPLORER_BACKING_READ`, `ExplorerSpec`,
  `TimelineWindow` (Task 2); `useContainer()` returning `{ timelines }`;
  `timelines.timeline(projectId, query)` where `query` is `TimelineWindowQuery`
  (`entityType?`, `from?`, `to?`, `limit?`, all optional and **absent rather than
  `undefined`**); `queryKeys.timeline(project, window)`; `resolvedWidgetQuery`; `ApiError`;
  `Timeline` (`@domain/knowledge/timeline.ts`); the `band`/`harness`/`PROJECT` module at
  `./timeline-widget-harness.tsx`; `componentBlock` from `@presentation/ask/ask-fixtures.ts`.
- Produces, for Tasks 4–6:

```tsx
export const ExplorerWidget: (props: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => React.ReactElement
```

  DOM contract Tasks 4–6 assert against: `[data-explorer-widget]` on the axis box,
  `.cmp-explorer-prompt` on the invitation, `.cmp-explorer-controls` on the fieldset,
  `.cmp-explorer-note` on the cannot-link sentence, a `<select>` labelled `Entity type`,
  `<input type="date">` labelled `From` and `To`, and `.cmp-timeline-counts` on the counts.

- [ ] **Step 1: Write the failing cost test**

Create `frontend/src/presentation/lesson/ExplorerWidget.cost.test.tsx`:

```tsx
/** What every reader interaction costs, which is the whole engineering content
 *  of this widget.
 *
 * Measured, not reasoned, and the measurement is upstream: `GET /timeline` is
 * two full passes over the tenant's entire entity set
 * (`timeline_reader.py:108-115`) and is deliberately uncached, and `limit`
 * never reaches the store (`graph_reader.py:294-299`) so it does not govern
 * that cost. A `timeline` block pays that once. An explorer hands the reader a
 * control that can pay it per keystroke.
 *
 * Alone in its own file rather than folded into `ExplorerWidget.test.tsx`,
 * deliberately. The design's section 7 calls this "the requirement most likely
 * to be quietly lost in a later refactor", and a file named for the
 * requirement is harder to delete by accident than three assertions among
 * twenty. It also means these run alone in a second while iterating.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { ExplorerWidget } from './ExplorerWidget.tsx'

vi.mock('../research/TimelineCanvas.tsx', () => ({
  TimelineCanvas: ({ bands }: { bands: readonly unknown[] }) => (
    <div data-testid="timeline-canvas" data-bands={bands.length} />
  ),
}))

const EXPLORER = {
  over: 'timeline',
  prompt: 'Pull the window back.',
  vary: ['entity_type', 'window'],
  from: '0300-01-01',
  to: '0400-01-01',
}

const mount = (data: Record<string, unknown> = EXPLORER) => {
  const timeline = vi
    .fn()
    .mockResolvedValue({ bands: [band('b1')], undatedCount: 0, truncated: false })
  render(
    <ExplorerWidget
      block={componentBlock({ type: 'explorer', id: 'e1', data })}
      attempts={{} as unknown as AttemptsApi}
      projectId={PROJECT}
    />,
    { wrapper: harness(timeline) },
  )
  return timeline
}

const from = () => screen.getByLabelText(/^from$/i)

/** A real macrotask gap, for the assertions that a request did *not* happen.
 *  `waitFor` cannot prove a negative and `await Promise.resolve()` does not
 *  drain a fetch TanStack Query would have scheduled. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 20))

it('issues one request when the window control is released, not one per change', async () => {
  // The failure this exists against is not hypothetical: a controlled
  // `<input type="date">` wired straight to the query key issues a request per
  // edit, so a reader adjusting a bound twice pays four full passes over the
  // corpus for one intention.
  //
  // Red against a widget that puts the draft value in the query key.
  const timeline = mount()
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(1))

  fireEvent.change(from(), { target: { value: '0200-01-01' } })
  fireEvent.change(from(), { target: { value: '0250-01-01' } })
  fireEvent.change(from(), { target: { value: '0280-01-01' } })

  // Nothing yet: three edits, and the reader has not finished deciding.
  expect(timeline).toHaveBeenCalledTimes(1)

  fireEvent.blur(from())

  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(2))
  expect(timeline).toHaveBeenLastCalledWith(PROJECT, {
    from: '0280-01-01',
    to: '0400-01-01',
  })
})

it('issues nothing at all when a released window is the one already showing', async () => {
  // A blur with no edit behind it -- tabbing through the controls -- must not
  // cost a double pass. Red against a widget that commits on every blur by
  // rebuilding the window object: `setState` to an equal *object* is not equal
  // to React, so the key changes identity and the query refires.
  const timeline = mount()
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(1))

  fireEvent.blur(from())
  fireEvent.blur(from())

  await settle()
  expect(timeline).toHaveBeenCalledTimes(1)
})

it('costs nothing to return to a parameter set already seen this session', async () => {
  // The second half of the design's section 4: "a reader returning to a
  // setting they already tried must not pay for it twice." This is what
  // `resolvedWidgetQuery`'s `staleTime` and `refetchOnMount: false` buy,
  // combined with a key carrying every bound.
  //
  // Red two ways, and both look fine on screen: a widget that omits
  // `...resolvedWidgetQuery` refetches the stale entry and comes back 3; a
  // widget keyed on the project alone never varies its key, comes back 1, and
  // shows the first window's bands under the third window's controls.
  const timeline = mount()
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(1))

  fireEvent.change(from(), { target: { value: '0200-01-01' } })
  fireEvent.blur(from())
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(2))

  fireEvent.change(from(), { target: { value: '0300-01-01' } })
  fireEvent.blur(from())

  await settle()
  expect(timeline).toHaveBeenCalledTimes(2)
})

it('asks once, not twice, when the author fixed no entity type', async () => {
  // The vocabulary read and the display read are the same request here: both
  // are built from `queryKeys.timeline` and both omit `entityType`, so
  // TanStack Query dedupes them to one fetch. That is the design's section 1
  // -- "one request gives the widget both its initial view and its full picker
  // vocabulary" -- and it holds only while the two keys are built the same
  // way. Red against a vocabulary query given a key of its own.
  const timeline = mount({ over: 'timeline', prompt: 'Look.', vary: ['entity_type', 'window'] })

  await waitFor(() => expect(screen.getByTestId('timeline-canvas')).toBeInTheDocument())
  await settle()
  expect(timeline).toHaveBeenCalledTimes(1)
})

it('pays a second read on mount only when the author fixed a type it must vary past', async () => {
  // The honest cost of the picker, asserted rather than tolerated: an explorer
  // that starts filtered needs an unfiltered read to know what else is in
  // there. Two reads, once, cached for the session -- not two per
  // interaction, which is what this number stops a later refactor becoming.
  const timeline = mount({ ...EXPLORER, entity_type: 'Person' })

  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(2))
  await settle()
  expect(timeline).toHaveBeenCalledTimes(2)
  expect(timeline.mock.calls.map((call) => call[1])).toEqual(
    expect.arrayContaining([
      { entityType: 'Person', from: '0300-01-01', to: '0400-01-01' },
      { from: '0300-01-01', to: '0400-01-01' },
    ]),
  )
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/lesson/ExplorerWidget.cost.test.tsx`

Expected: FAIL — cannot resolve `./ExplorerWidget.tsx`.

- [ ] **Step 3: Write the widget**

Create `frontend/src/presentation/lesson/ExplorerWidget.tsx`:

```tsx
import type { UseQueryResult } from '@tanstack/react-query'
import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useId, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ApiError } from '@application/ports/errors.ts'
import type { TimelineWindowQuery } from '@application/ports/repositories.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { resolvedWidgetQuery } from '@application/queries/resolved-widget.ts'
import type { Timeline } from '@domain/knowledge/timeline.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { ExplorerSpec, TimelineWindow } from '@domain/lesson/widgets.ts'
import { EXPLORER_BACKING_READ, readExplorerQuery, varies } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

// Lazy for `TimelineWidget`'s reason: the axis is a drawing a reader mostly is
// not looking at, and it should be fetched when one actually meets an explorer.
const TimelineCanvas = lazy(() =>
  import('../research/TimelineCanvas.tsx').then((module) => ({ default: module.TimelineCanvas })),
)

/** A timeline the reader re-runs.
 *
 * **The one thing to know before editing this file: every reader interaction
 * costs a full pass over the tenant's entity set, twice.** `GET /timeline` is
 * two passes (`timeline_reader.py:108-115`) and is deliberately uncached, and
 * `limit` never reaches the store (`graph_reader.py:294-299`) so it does not
 * govern that cost. That is why the window control commits on blur rather than
 * on change, and why every distinct parameter set is a distinct query key
 * cached for the session. `ExplorerWidget.cost.test.tsx` fails if either half
 * is lost.
 *
 * **Two queries, one cache.** The display query carries the reader's whole
 * parameter set; the vocabulary query is the same window with no entity type,
 * and it exists because no route enumerates the known types -- the only
 * complete vocabulary available is the set present in an unfiltered response.
 * Both are keyed through `queryKeys.timeline`, so when the author fixed no
 * `entity_type` the two keys are identical and there is one request. When they
 * did fix one it is two reads on mount, once, cached for the session; the cost
 * test asserts that number rather than leaving it to be discovered.
 *
 * **The vocabulary is only as complete as an uncapped response.** The server
 * caps bands, so a type present only past the cap is not offered. That is a
 * real gap, and it is why `truncated` is rendered here as it is in `timeline`:
 * telling the reader the answer was capped is the only honest thing this build
 * can say about it.
 *
 * `attempts` is in the signature and unused, for `DefinitionWidget`'s reason:
 * every entry in `RENDERERS` takes it, and a resolved component is not
 * gradeable.
 */
export const ExplorerWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const spec = readExplorerQuery(block)

  if (spec.over !== EXPLORER_BACKING_READ) {
    // Prose, and it names what *is* supported. The server warned rather than
    // rejected this (see `_explorer_over`), so the block is renderable and this
    // sentence is the whole of what renders -- an author who wrote
    // `over: graph` learns here that the corpus cannot be asked that yet.
    return (
      <div className="cmp-body">
        <p className="cmp-ref-note">
          This explorer asks to range over “{spec.over}”, and only “{EXPLORER_BACKING_READ}”
          can be explored in this build.
        </p>
      </div>
    )
  }

  if (!projectId) {
    // `TimelineWidget`'s `unavailable` state, drawn here rather than by
    // `ResolvedFrame` for the same reason: there is no entity reference to
    // frame, and the honest degradation is a sentence.
    return (
      <div className="cmp-body">
        <p className="cmp-ref-note">
          An explorer needs a project in scope, and this page has none.
        </p>
      </div>
    )
  }

  return (
    <div className="cmp-body">
      <p className="cmp-explorer-prompt">{spec.prompt}</p>
      <Exploring projectId={projectId} spec={spec} />
    </div>
  )
}

/** The window as the port wants it: absent keys rather than nulls, so an
 *  omitted bound stays an open end all the way to the query string and
 *  `exactOptionalPropertyTypes` is satisfied without an explicit `undefined`.
 *
 * Copied from `TimelineWidget` rather than shared. The two diverge the day
 * either grows an axis the other does not have, and a shared helper would make
 * that a change to both files. */
const asQuery = (window: TimelineWindow): TimelineWindowQuery => ({
  ...(window.entityType ? { entityType: window.entityType } : {}),
  ...(window.from ? { from: window.from } : {}),
  ...(window.to ? { to: window.to } : {}),
  ...(window.limit === null ? {} : { limit: window.limit }),
})

/** Split out so the hooks mount only once there is a project and a supported
 *  backing read to give them -- a hook cannot be called conditionally. */
const Exploring = ({ projectId, spec }: { projectId: ProjectId; spec: ExplorerSpec }) => {
  const { timelines } = useContainer()
  // The committed parameter set. Drafts live in `Controls` and arrive here only
  // on release, which is the whole cost design in one line.
  const [window, setWindow] = useState<TimelineWindow>(spec.window)

  const result = useQuery({
    queryKey: queryKeys.timeline(projectId, window),
    queryFn: () => timelines.timeline(projectId, asQuery(window)),
    ...resolvedWidgetQuery,
  })

  // The same key builder, the same window, `entityType` dropped. Identical to
  // the display key whenever the reader has no type selected, which is what
  // makes the common case one request rather than two.
  const vocabularyWindow: TimelineWindow = { ...window, entityType: null }
  const vocabulary = useQuery({
    queryKey: queryKeys.timeline(projectId, vocabularyWindow),
    queryFn: () => timelines.timeline(projectId, asQuery(vocabularyWindow)),
    enabled: varies(spec, 'entity_type'),
    ...resolvedWidgetQuery,
  })

  // Sorted so the picker does not reorder itself between renders as bands
  // arrive in a different order; deduplicated because a corpus has many
  // entities per type and the picker offers types.
  const types = [
    ...new Set((vocabulary.data?.bands ?? []).map((entry) => entry.entityType).filter(Boolean)),
  ].sort()

  return (
    <>
      <Controls spec={spec} window={window} types={types} onCommit={setWindow} />
      <Result result={result} />
    </>
  )
}

/** The controls the author opened, and nothing else.
 *
 * A `<fieldset>` rather than a `<form>`: there is nothing to submit, and a form
 * inside an answer would swallow an Enter key the surrounding page may want.
 */
const Controls = ({
  spec,
  window,
  types,
  onCommit,
}: {
  spec: ExplorerSpec
  window: TimelineWindow
  types: readonly string[]
  onCommit: (next: TimelineWindow) => void
}) => {
  const [draft, setDraft] = useState({ from: window.from ?? '', to: window.to ?? '' })
  const ids = useId()

  // Commits only when something actually changed. A blur with no edit behind it
  // -- tabbing through -- must not cost a double pass, and `setState` to an
  // equal *object* is not equal to React, so the comparison is on the fields.
  const commitWindow = () => {
    const from = draft.from || null
    const to = draft.to || null
    if (from === window.from && to === window.to) return
    onCommit({ ...window, from, to })
  }

  return (
    <fieldset className="cmp-explorer-controls">
      <legend className="cmp-explorer-legend">Explore</legend>
      {varies(spec, 'entity_type') ? (
        <label className="cmp-explorer-field" htmlFor={`${ids}-type`}>
          <span>Entity type</span>
          <select
            id={`${ids}-type`}
            value={window.entityType ?? ''}
            // A select commits on change, because a change *is* the release:
            // one discrete choice, one request. Unlike a date box there is no
            // intermediate value a reader passes through on the way.
            onChange={(event) => {
              onCommit({ ...window, entityType: event.target.value || null })
            }}
          >
            <option value="">any type</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {varies(spec, 'window') ? (
        <>
          <label className="cmp-explorer-field" htmlFor={`${ids}-from`}>
            <span>From</span>
            {/* `type="date"` rather than a text box, per the design's section
                4: the control produces `YYYY-MM-DD`, which is the format the
                route parses, instead of accepting free text and reporting a 422
                the reader cannot act on. */}
            <input
              id={`${ids}-from`}
              type="date"
              value={draft.from}
              onChange={(event) => {
                setDraft({ ...draft, from: event.target.value })
              }}
              onBlur={commitWindow}
            />
          </label>
          <label className="cmp-explorer-field" htmlFor={`${ids}-to`}>
            <span>To</span>
            <input
              id={`${ids}-to`}
              type="date"
              value={draft.to}
              onChange={(event) => {
                setDraft({ ...draft, to: event.target.value })
              }}
              onBlur={commitWindow}
            />
          </label>
        </>
      ) : null}
      {/* Said out loud rather than left for a reader to discover. The design's
          section 5: no filter state is serialised into the URL anywhere in this
          app, so a view cannot be linked to, and a share affordance would be
          one that does not work. */}
      <p className="cmp-explorer-note">
        What you find here cannot be linked to — take a screenshot to keep it.
      </p>
    </fieldset>
  )
}

/** The drawing and the counts. Duplicated from `TimelineWidget` for `asQuery`'s
 *  reason, and because the error prose differs: an explorer's unparseable bound
 *  is usually the *reader*'s doing rather than the author's. */
const Result = ({ result }: { result: UseQueryResult<Timeline> }) => {
  if (result.isPending) return <p className="cmp-ref-note">reading the timeline…</p>
  if (result.isError || !result.data) {
    const unparseable = result.error instanceof ApiError && result.error.status === 422
    return (
      <p className="cmp-ref-note">
        {unparseable
          ? 'One of those bounds could not be read as a date, so nothing was drawn.'
          : 'This project’s timeline could not be read just now.'}
      </p>
    )
  }

  const { bands, undatedCount, truncated } = result.data

  return (
    <>
      {bands.length === 0 ? (
        <p className="cmp-ref-note">Nothing dated matches that window in this project.</p>
      ) : (
        <div className="cmp-timeline-box" data-explorer-widget>
          <Suspense fallback={<p className="cmp-ref-note">loading the axis…</p>}>
            {/* `onSelect` is a no-op deliberately, copying `TimelineWidget`: a
                block inside an answer has no detail panel to open. */}
            <TimelineCanvas bands={bands} selected={null} onSelect={() => {}} />
          </Suspense>
        </div>
      )}
      {/* Rendered on every result including the empty one, and it matters more
          here than in `timeline`: a reader narrowing a filter and watching bands
          vanish needs to know which vanished because they were excluded and
          which because the response was capped. */}
      <p className="cmp-timeline-counts">
        {bands.length} dated
        {undatedCount > 0 ? `, ${undatedCount} with no dates at all` : ''}
        {truncated ? ' — more than could be shown' : ''}
      </p>
    </>
  )
}
```

- [ ] **Step 4: Run the cost test to verify it passes**

Run: `cd frontend && npx vitest run src/presentation/lesson/ExplorerWidget.cost.test.tsx`

Expected: PASS, 5 tests. If one fails, re-run it alone before investigating — and never
alongside another vitest process.

- [ ] **Step 5: Prove the first cost test red before trusting it green**

Temporarily delete the early return from `commitWindow` and change the two `onChange`
handlers to call `commitWindow`-equivalent logic directly:

```tsx
onChange={(event) => {
  onCommit({ ...window, from: event.target.value || null })
}}
```

Re-run the cost test. Expected: the first test fails with `expected 1, received 4` — four full
double passes over the corpus for one reader intention. Revert.

This is the repository's convention (`CLAUDE.md`, "Comments and commit messages"), and it is
the one test in this plan where it is not optional.

- [ ] **Step 6: Wiring**

Run: `cd frontend && grep -n "timelines" src/app/container.ts`

Expected: the container really exposes `timelines`, plural. The test harness casts through
`as unknown as AppContainer`, so a singular `timeline` key would typecheck cleanly, resolve to
`undefined`, and leave the widget in `isPending` forever with every test still green — which
is why `timeline-widget-harness.tsx` names the key in one place and says so in a comment.

The widget is not in `RENDERERS` yet, so nothing outside its own tests renders it. That is
Task 6, and it is stated here so the gap is not mistaken for done.

- [ ] **Step 7: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 8: Commit**

```bash
git add frontend/src/presentation/lesson/ExplorerWidget.tsx \
  frontend/src/presentation/lesson/ExplorerWidget.cost.test.tsx \
  research_team/interfaces/web/static
git commit -m "Explore a timeline at a cost the widget actually bounds

The cost test is the first thing in this feature and is alone in its own file,
because it is the requirement a later refactor loses silently: GET /timeline is
two full passes over the tenant's entity set and is uncached, and a controlled
date input wired straight to a query key issues one per keystroke. So the
window commits on blur, and only when something changed -- a blur with no edit
behind it costs nothing, which a naive implementation gets wrong by rebuilding
the window object and changing its identity.

Proved red before trusting it green: with onChange committing directly, the
first test comes back 4 requests for one intention.

Two queries share one cache. The vocabulary read exists because no route
enumerates entity types, so the only complete vocabulary is the set present in
an unfiltered response. Both keys come from queryKeys.timeline, so when the
author fixed no type the keys are identical and there is one request; when they
did, it is two on mount, once per session, and the cost test asserts that
number rather than tolerating it.

What this cannot do, and says so on screen: link to a view. No filter state is
serialised into a URL anywhere in this app, so a share affordance would be one
that does not work. The controls carry a sentence saying to screenshot instead.

Costs accepted: asQuery and the counts line are duplicated from TimelineWidget
rather than extracted. The two diverge the day either grows an axis the other
lacks, and a shared helper would make that a change to both files -- and the
error prose already differs, because an explorer's bad bound is usually the
reader's rather than the author's.

Not wired into RENDERERS yet; that lands with the end-to-end test."
```

---

### Task 4: The rest of what jsdom can judge

**Files:**
- Create: `frontend/src/presentation/lesson/ExplorerWidget.test.tsx`
- Modify: `frontend/src/presentation/lesson/ExplorerWidget.tsx` (only if a test finds a gap)

**Interfaces:**
- Consumes: `ExplorerWidget` and its DOM contract from Task 3; `band`/`harness`/`PROJECT`;
  `componentBlock`; `ApiError`.
- Produces: nothing new. This task adds coverage only.

- [ ] **Step 1: Write the tests**

Create `frontend/src/presentation/lesson/ExplorerWidget.test.tsx`:

```tsx
/** What jsdom can judge about the explorer: the requests each control makes,
 *  the prose it falls back to, and the counts it is obliged to show on every
 *  result.
 *
 * The cost behaviour is deliberately not here -- it lives alone in
 * `ExplorerWidget.cost.test.tsx`, for the reason that file's docstring gives.
 * The height assertion is in `ExplorerWidget.browser.test.tsx`, for CLAUDE.md's
 * reason: jsdom lays nothing out.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ApiError } from '@application/ports/errors.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { ExplorerWidget } from './ExplorerWidget.tsx'

vi.mock('../research/TimelineCanvas.tsx', () => ({
  TimelineCanvas: ({ bands }: { bands: readonly unknown[] }) => (
    <div data-testid="timeline-canvas" data-bands={bands.length} />
  ),
}))

const attempts = {} as unknown as AttemptsApi

const BASE = {
  over: 'timeline',
  prompt: 'Pull the window back.',
  vary: ['entity_type', 'window'],
}

const renderWidget = (
  data: Record<string, unknown> = BASE,
  {
    timeline = vi
      .fn()
      .mockResolvedValue({ bands: [band('b1')], undatedCount: 0, truncated: false }),
    // `null` and not `undefined` for "no project in scope": a destructuring
    // default fires on `undefined` and would restore `PROJECT`, so the
    // no-project test would silently exercise the ordinary path -- the shape
    // `EvidenceWidget.test.tsx` records having measured.
    projectId = PROJECT,
  }: { timeline?: ReturnType<typeof vi.fn>; projectId?: ProjectId | null } = {},
) => ({
  timeline,
  ...render(
    <ExplorerWidget
      block={componentBlock({ type: 'explorer', id: 'e1', data })}
      attempts={attempts}
      {...(projectId ? { projectId } : {})}
    />,
    { wrapper: harness(timeline) },
  ),
})

it('reads the author’s window first, before the reader has touched anything', async () => {
  const { timeline } = renderWidget({ ...BASE, entity_type: 'Person', from: '0300-01-01' })

  await waitFor(() =>
    expect(timeline).toHaveBeenCalledWith(PROJECT, {
      entityType: 'Person',
      from: '0300-01-01',
    }),
  )
})

it('offers every entity type the unfiltered read came back with', async () => {
  // The design's section 1 in one assertion: no route enumerates entity types,
  // so the picker's vocabulary is whatever an unfiltered response contains.
  //
  // Red against a picker populated from the *filtered* response, which on a
  // widget the author started at `Person` would offer exactly one option --
  // the one already chosen -- and would look entirely reasonable on screen.
  const timeline = vi.fn().mockImplementation((_project, window: { entityType?: string }) =>
    Promise.resolve({
      bands: window.entityType
        ? [band('p1')]
        : [
            { ...band('p1'), entityType: 'Person' },
            { ...band('w1'), entityType: 'Work' },
            { ...band('p2'), entityType: 'Person' },
          ],
      undatedCount: 0,
      truncated: false,
    }),
  )
  renderWidget({ ...BASE, entity_type: 'Person' }, { timeline })

  await waitFor(() => expect(screen.getByRole('option', { name: 'Work' })).toBeInTheDocument())
  // Deduplicated and sorted: two `Person` bands are one option, and the order
  // does not depend on the order bands arrived in.
  expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([
    'any type',
    'Person',
    'Work',
  ])
})

it('re-reads with the type the reader chose', async () => {
  const { timeline } = renderWidget({ ...BASE, from: '0300-01-01' })
  await waitFor(() => expect(timeline).toHaveBeenCalled())

  fireEvent.change(screen.getByLabelText(/entity type/i), { target: { value: 'Person' } })

  await waitFor(() =>
    expect(timeline).toHaveBeenLastCalledWith(PROJECT, {
      entityType: 'Person',
      from: '0300-01-01',
    }),
  )
})

it('draws only the controls the author opened', () => {
  // `vary` is not a formality: an author who set a window deliberately and one
  // who did not are indistinguishable to a reader unless the author says which.
  // Red against a widget defaulting `vary` to every axis.
  renderWidget({ ...BASE, vary: ['entity_type'] })

  expect(screen.getByLabelText(/entity type/i)).toBeInTheDocument()
  expect(screen.queryByLabelText(/^from$/i)).not.toBeInTheDocument()
  expect(screen.queryByLabelText(/^to$/i)).not.toBeInTheDocument()
})

it('renders an unsupported backing read as prose naming what is supported', () => {
  // The `over:` seam. The server warns rather than rejects, so this block is
  // valid and arrives renderable -- and the sentence has to name `timeline`,
  // because "not supported" alone tells an author nothing they can act on.
  const { timeline } = renderWidget({ ...BASE, over: 'graph' })

  expect(screen.getByText(/only/i)).toHaveTextContent('timeline')
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  expect(timeline).not.toHaveBeenCalled()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('shows the author’s invitation, which is the point of the type', () => {
  // Without the prompt a reader is handed controls with no reason to touch
  // them, which is the design's section 3. Red against a widget that reads
  // `prompt` and never renders it.
  renderWidget({ ...BASE, prompt: 'Pull the window back to the third century.' })

  expect(screen.getByText(/third century/)).toBeInTheDocument()
})

it('says how many entities carry no dates at all, on every result', async () => {
  renderWidget(BASE, {
    timeline: vi
      .fn()
      .mockResolvedValue({ bands: [band('b1')], undatedCount: 412, truncated: false }),
  })

  await waitFor(() => expect(screen.getByText(/412/)).toBeInTheDocument())
})

it('still reports the counts when the reader has narrowed to nothing', async () => {
  // The state an explorer reaches and a timeline mostly does not: a reader
  // narrows, the bands vanish, and without the counts they cannot tell
  // exclusion from truncation. Red against a widget that returns early on an
  // empty `bands` and never reaches the counts.
  renderWidget(BASE, {
    timeline: vi.fn().mockResolvedValue({ bands: [], undatedCount: 412, truncated: true }),
  })

  await waitFor(() => expect(screen.getByText(/412/)).toBeInTheDocument())
  expect(screen.getByText(/more than could be shown/i)).toBeInTheDocument()
  expect(screen.getByText(/nothing dated/i)).toBeInTheDocument()
})

it('blames the bound rather than the project when a date will not parse', async () => {
  renderWidget(BASE, {
    timeline: vi.fn().mockRejectedValue(new ApiError("'from' is not an ISO instant", 422)),
  })

  await waitFor(() =>
    expect(screen.getByText(/could not be read as a date/i)).toBeInTheDocument(),
  )
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('tells the reader a view cannot be linked to', () => {
  // The design's section 5: no query state is serialisable anywhere in this
  // app, so saying so is better than a share affordance that does not work.
  // Matched without an apostrophe: this build emits typographic ones and a
  // straight-quote regex would never match.
  renderWidget(BASE)

  expect(screen.getByText(/cannot be linked to/i)).toBeInTheDocument()
})

it('renders nothing but a note with no project in scope, and fetches nothing', () => {
  const { timeline } = renderWidget(BASE, { projectId: null })

  expect(timeline).not.toHaveBeenCalled()
  expect(screen.getByText(/needs a project in scope/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run them**

Run: `cd frontend && npx vitest run src/presentation/lesson/ExplorerWidget.test.tsx`

Expected: PASS, 11 tests. If `offers every entity type…` fails on order, fix the test's
expectation rather than the widget: `types` is sorted on purpose so the picker does not
reorder itself between renders.

- [ ] **Step 3: Wiring**

Run: `cd frontend && npx vitest run src/presentation/lesson/ src/domain/lesson/`

Expected: PASS, including the existing `TimelineWidget` suites — this task shares their
harness module, and any change to `band()` to suit the explorer would silently weaken
`TimelineWidget.browser.test.tsx`, which renders the real canvas and measures it. If you did
have to change `timeline-widget-harness.tsx`, run `npm run test:browser` before continuing.

- [ ] **Step 4: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/presentation/lesson/ExplorerWidget.test.tsx \
  frontend/src/presentation/lesson/ExplorerWidget.tsx \
  research_team/interfaces/web/static
git commit -m "Cover what jsdom can judge about the explorer

The picker-vocabulary test is the one worth reading twice: it stubs the
repository to answer differently for a filtered and an unfiltered window, so a
picker populated from the filtered response comes back offering exactly one
option -- the one already chosen. That failure looks completely fine on screen
and is the whole reason the vocabulary query exists.

vary is asserted as a restriction rather than as a default. An author who set a
window deliberately and one who did not are indistinguishable to a reader
unless the author says which, and a widget that defaulted vary to everything
would pass a test that only checked the controls were present.

The counts are asserted on the empty result specifically. That is the state an
explorer reaches and a timeline mostly does not: a reader narrows, the bands
vanish, and without the counts they cannot tell exclusion from truncation."
```

---

### Task 5: The control row's dressing, and a measured height

**Files:**
- Modify: `frontend/src/styles/components.css` (after the `.cmp-timeline-counts` rule at ~805)
- Create: `frontend/src/presentation/lesson/ExplorerWidget.browser.test.tsx`

**Interfaces:**
- Consumes: `.cmp-timeline-box` and `.cmp-timeline-counts` (reused verbatim); tokens
  `--fg`, `--fg-dim`, `--bg-raise`, `--t-sm`, `--radius`. **Grep `tokens.css` before naming
  any other.**
- Produces: `.cmp-explorer-prompt`, `.cmp-explorer-controls`, `.cmp-explorer-legend`,
  `.cmp-explorer-field`, `.cmp-explorer-note`.

- [ ] **Step 1: Confirm every token exists before writing a rule**

Run: `cd frontend && grep -nE -- "--(fg|fg-dim|bg-raise|t-sm|radius):" src/styles/tokens.css`

Expected: one hit each. A miss means the rule you were about to write sets nothing and looks
exactly like one that worked — `--fg-muted` and `--bg-raised` are the two this feature's
briefs have already got wrong.

- [ ] **Step 2: Write the CSS**

Append to `frontend/src/styles/components.css`, after `.cmp-timeline-counts`:

```css
/* The explorer reuses `.cmp-timeline-box` for its axis verbatim -- it is the
   same drawing in the same kind of flow, and a second box rule would be a
   second thing to keep in step with the measurement in
   `TimelineWidget.browser.test.tsx`. Only the control row is new. */

/* The invitation, and the one thing that makes this worth more than a
   timeline. Body colour and not `--fg-dim`: this is prose the author wrote for
   the reader to act on, not an aside about the widget. */
.cmp-explorer-prompt {
  margin: 0 0 0.75rem;
  color: var(--fg);
}

.cmp-explorer-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.75rem;
  margin: 0 0 0.75rem;
  padding: 0.75rem;
  /* `border: 0` and no directional width: this row has no rule. The pairing is
     written out so that adding one later cannot fall into the `border-solid`
     trap CLAUDE.md records -- a `<fieldset>` carries a UA border, so leaving
     this off would draw one nobody asked for. */
  border: 0;
  border-radius: var(--radius);
  background: var(--bg-raise);
}

/* A `<legend>` inside a flex `<fieldset>` is laid out by the UA rather than by
   the flex container, which is why this is only coloured and padded. */
.cmp-explorer-legend {
  padding: 0 0.25rem;
  font-size: var(--t-sm);
  color: var(--fg-dim);
}

.cmp-explorer-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: var(--t-sm);
  color: var(--fg-dim);
}

/* Full-width so it sits under the controls rather than beside them: it is a
   statement about the whole row, and a reader scanning left to right for the
   next control should not find a sentence there. */
.cmp-explorer-note {
  flex-basis: 100%;
  margin: 0;
  font-size: var(--t-sm);
  color: var(--fg-dim);
}
```

- [ ] **Step 3: Write the browser test**

Create `frontend/src/presentation/lesson/ExplorerWidget.browser.test.tsx`:

```tsx
/** That the explorer has a height, and that its control row does not eat it.
 *
 * `TimelineCanvas` is pure SVG sized by its container, and a markdown flow
 * gives it none. jsdom reports `0x0` here whatever `.cmp-timeline-box` says, so
 * this is the suite that can judge it -- the same assertion `graph` and
 * `timeline` both needed, for the same reason.
 *
 * The canvas is *not* mocked, unlike the jsdom suites: `TimelineCanvas` returns
 * `null` when `spanOf(bands)` is null (`TimelineCanvas.tsx:120`), so a fixture
 * with no usable dates would measure an empty box and pass for the wrong
 * reason. The bands come from the shared harness for that reason.
 *
 * The wrapper is a real `.md.doc` flow rather than a bare div, because that is
 * the context the widget lands in and the height it gets is a property of that
 * context. The viewport is set in `vite.config.ts`, not by this wrapper's width
 * -- if a media query ever governs this row, that is the file to read.
 */
import { expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { ExplorerWidget } from './ExplorerWidget.tsx'

it('gives the axis a box with a real height below its controls', async () => {
  const timeline = vi.fn().mockResolvedValue({
    // Two bands with distinct bounds: one instant is a zero-width span the
    // canvas special-cases, and a test on that path would be measuring the
    // special case rather than the ordinary drawing.
    bands: [band('b1', '0300-01-01', '0330-01-01'), band('b2', '0350-01-01', '0400-01-01')],
    undatedCount: 412,
    truncated: false,
  })
  const Harness = harness(timeline)
  const screen = await render(
    <Harness>
      <div className="md doc" style={{ width: '640px' }}>
        <p>Prose before the widget.</p>
        <ExplorerWidget
          block={componentBlock({
            type: 'explorer',
            id: 'fourth-century-explorer',
            data: {
              over: 'timeline',
              prompt: 'Pull the window back.',
              vary: ['entity_type', 'window'],
              from: '0300-01-01',
              to: '0400-01-01',
            },
          })}
          attempts={{} as unknown as AttemptsApi}
          projectId={PROJECT}
        />
        <p>Prose after it.</p>
      </div>
    </Harness>,
  )

  // Polls on the canvas's own `svg`, not on the box: the box appears as soon as
  // the query settles while `TimelineCanvas` is behind `React.lazy` and arrives
  // a microtask later. Waiting on the box alone reaches the measurement with
  // the `Suspense` fallback still up -- and would pass even if the canvas
  // rendered `null` for want of a usable span.
  await vi.waitFor(() => {
    expect(screen.container.querySelector('[data-explorer-widget] svg')).not.toBeNull()
  })

  const measured = screen.container.querySelector('[data-explorer-widget]') as HTMLElement
  const rect = measured.getBoundingClientRect()

  expect(rect.width).toBeGreaterThan(300)
  expect(rect.height).toBeGreaterThan(150)

  // An undefined custom property sets no background at all and resolves to a
  // transparent computed value, which is how `--bg-raised` (not a token this
  // build defines) would have shipped looking like a rule that worked.
  expect(getComputedStyle(measured).backgroundColor).not.toBe('rgba(0, 0, 0, 0)')

  // The controls are above the drawing rather than over it. `.cmp-timeline-box`
  // sets `position: relative` so the canvas's absolutely positioned children
  // resolve against it; a control row that ended up inside that containing
  // block would draw across the axis while every other assertion here still
  // passed.
  const controls = screen.container.querySelector('.cmp-explorer-controls') as HTMLElement
  const controlRect = controls.getBoundingClientRect()
  expect(controlRect.height).toBeGreaterThan(20)
  expect(controlRect.bottom).toBeLessThanOrEqual(rect.top)

  // The counts read as an aside. Compared against the surrounding prose rather
  // than to a literal, so a token value change does not fail this -- and
  // `--fg-muted` is the undefined token that would leave them in body colour,
  // which looks fine and simply stops reading as an aside.
  const counts = screen.container.querySelector('.cmp-timeline-counts') as HTMLElement
  const prose = screen.container.querySelector('.md.doc > p') as HTMLElement
  expect(counts.textContent).toContain('412')
  expect(getComputedStyle(counts).color).not.toBe(getComputedStyle(prose).color)
})
```

- [ ] **Step 4: Run it**

Run: `cd frontend && npm run test:browser`

Expected: PASS. This suite is not in `verify` and not in CI — it runs only because someone ran
it. Make sure no other vitest process is running first.

- [ ] **Step 5: Prove the height assertion red**

Comment `min-height: 12rem` out of `.cmp-timeline-box`, re-run `npm run test:browser`, and
confirm this test fails on `rect.height` — and that `TimelineWidget.browser.test.tsx` fails
with it. Restore the rule.

That second half is the point: it is also the check that the two suites are measuring the same
rule rather than two rules that happen to agree.

- [ ] **Step 6: Wiring**

Run: `cd frontend && grep -n "cmp-explorer" src/presentation/lesson/ExplorerWidget.tsx src/styles/components.css`

Every class in the stylesheet must appear in the widget and every class in the widget must
appear in the stylesheet. A class in only one place is inert and no gate catches it — the same
shape as the `RING_INWARD` failure CLAUDE.md records, where the class was in the attribute and
the rule was in the bundle and only the computed value disagreed.

- [ ] **Step 7: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 8: Commit**

```bash
git add frontend/src/styles/components.css \
  frontend/src/presentation/lesson/ExplorerWidget.browser.test.tsx \
  research_team/interfaces/web/static
git commit -m "Dress the explorer's controls, and measure that the axis still has a height

Reuses .cmp-timeline-box verbatim rather than adding a second box rule: it is
the same drawing in the same kind of flow, and a copy would be a second thing
to keep in step with the measurement TimelineWidget.browser.test.tsx already
takes. Proved by commenting min-height out and watching both suites fail --
which is also the check that the two are measuring one rule and not two that
happen to agree.

The assertion this feature needed beyond timeline's is that the control row
sits above the drawing rather than inside it. .cmp-timeline-box sets
position: relative so the canvas's absolute children resolve against it, and a
control row that ended up inside that containing block would draw across the
axis while every height, width and colour assertion still passed.

border: 0 on the fieldset is not decoration: a fieldset carries a UA border,
and the pairing is written out so a directional width added later cannot fall
into the border-solid trap.

Tokens grepped against tokens.css, not reasoned. --fg-muted and --bg-raised do
not exist here and set nothing while looking like rules that worked; the
browser test asserts against a transparent computed background for exactly
that reason.

This suite is outside verify and outside CI on purpose, so it runs only because
someone ran it. Run it when this stylesheet is next edited."
```

---

### Task 6: Wire it into `RENDERERS`, and prove the seam end to end

**Files:**
- Modify: `frontend/src/presentation/lesson/LessonDocument.tsx` (import beside line 15;
  `RENDERERS` at lines 101-111)
- Create: `frontend/src/presentation/lesson/LessonDocument.explorer.test.tsx`

**Interfaces:**
- Consumes: `ExplorerWidget` (Task 3), the wire body Task 1 produces, `LessonDocument`'s own
  props — read them from the file and copy the shape `AskTurn.tsx:110-113` uses
  (`doc={{ blocks: turn.blocks }}`).
- Produces: `RENDERERS.explorer`. Nothing depends on this task; it is the last link.

- [ ] **Step 1: Write the failing end-to-end test**

Create `frontend/src/presentation/lesson/LessonDocument.explorer.test.tsx`:

````tsx
/** The seam, and only the seam: that a block the server typed `explorer`
 *  reaches `ExplorerWidget` rather than the unknown-fence path.
 *
 * This is the assertion CLAUDE.md's `EntityDefinitionRunner` paragraph is
 * about. A component that is registered, validated, projected, serialised and
 * fully implemented, and is simply absent from `RENDERERS`, renders as a
 * `<pre>` -- nothing raises, nothing logs, the request succeeds, and every
 * unit test in this feature stays green. The failure is visible only by
 * looking, or by this.
 *
 * Deliberately does not assert on what the widget draws. That is
 * `ExplorerWidget.test.tsx`'s job, and duplicating it here would make this file
 * fail for reasons that have nothing to do with the wiring.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { LessonDocument } from './LessonDocument.tsx'

vi.mock('../research/TimelineCanvas.tsx', () => ({
  TimelineCanvas: () => <div data-testid="timeline-canvas" />,
}))

it('routes an explorer block to the explorer widget, not to the unknown fence', async () => {
  const timeline = vi
    .fn()
    .mockResolvedValue({ bands: [band('b1')], undatedCount: 3, truncated: false })

  render(
    <LessonDocument
      doc={{
        blocks: [
          { kind: 'markdown', text: 'Some prose.' },
          componentBlock({
            type: 'explorer',
            id: 'e1',
            data: {
              over: 'timeline',
              prompt: 'Pull the window back.',
              vary: ['window'],
              from: '0300-01-01',
            },
          }),
        ],
      }}
      attempts={{} as unknown as AttemptsApi}
      projectId={PROJECT}
    />,
    { wrapper: harness(timeline) },
  )

  // The two halves of "wired", and both are needed. The section label is
  // `LessonDocument`'s own frame and proves the type was recognised; the
  // request proves `projectId` was threaded through to the widget. A widget
  // rendered without a project satisfies the first and draws a sentence saying
  // it cannot look anything up.
  expect(screen.getByLabelText('explorer component')).toBeInTheDocument()
  await waitFor(() => expect(timeline).toHaveBeenCalledWith(PROJECT, { from: '0300-01-01' }))
  expect(screen.queryByText(/```component:explorer/)).not.toBeInTheDocument()
})
````

Before running, read `frontend/src/presentation/lesson/LessonDocument.tsx` and match its real
prop names exactly — this plan does not restate them, and a guess here fails as a type error
rather than as the wiring failure the test is for.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/lesson/LessonDocument.explorer.test.tsx`

Expected: FAIL — `Unable to find a label with the text of: explorer component`, because the
block took the `UnknownComponent` path. **This is the failure the whole task exists for; do
not skip watching it happen.**

- [ ] **Step 3: Add the two lines**

In `frontend/src/presentation/lesson/LessonDocument.tsx`, beside the existing
`import { TimelineWidget } from './TimelineWidget.tsx'`:

```tsx
import { ExplorerWidget } from './ExplorerWidget.tsx'
```

and in `RENDERERS`, after `compare`:

```tsx
  explorer: ExplorerWidget,
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/presentation/lesson/LessonDocument.explorer.test.tsx`

Expected: PASS.

- [ ] **Step 5: Wiring — the whole chain, in one read**

Confirm each link. Every one has an owner task; this is the step where they meet.

| Link | Where | Confirm |
| --- | --- | --- |
| registry | `components.py` `REGISTRY["explorer"]` | `resolved=True`, seven fields, `warn` set |
| authoring | `ask_agent.py` `ASK_PROMPT` | contains `component:explorer` |
| parse + project | `ask_components.answer_document` | `data` unstripped, `withheld == []` |
| SSE answer frame | `app.py:2966` and `app.py:3113` | both call `answer_document`; neither filters by type |
| DTO / mapper | `frontend/src/infrastructure/http/` | **nothing to change** — a block is an open record on the wire; confirm by finding no type allowlist |
| domain reader | `widgets.ts` `readExplorerQuery` | field names match the registry's, `snake_case` |
| `RENDERERS` | `LessonDocument.tsx` | `explorer: ExplorerWidget` |
| widget → port | `ExplorerWidget.tsx` | `timelines.timeline(...)`, plural key |

Run: `cd frontend && grep -rn "'mcq'" src/infrastructure src/application`

Expected: no hits outside tests. If a hardcoded component-type list exists anywhere in the
infrastructure or application layer, `explorer` has to join it and this table is a row short.

- [ ] **Step 6: All four gates, plus the browser suite**

Run, in order and one at a time:
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `cd frontend && npm run verify`
- `cd frontend && npm run test:browser` (alone — no other vitest process)
- `cd frontend && npm run build`

- [ ] **Step 7: Confirm the committed build has no drift**

Run: `git status --porcelain research_team/interfaces/web/static`

If this prints anything after `npm run build`, those files belong in the commit. That is the
fifth gate, and it is the one `verify` passes green over.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/presentation/lesson/LessonDocument.tsx \
  frontend/src/presentation/lesson/LessonDocument.explorer.test.tsx \
  research_team/interfaces/web/static
git commit -m "Route an explorer block to the explorer widget

Two lines of source and a test worth more than both. A component can be
registered, validated, projected, serialised and fully implemented and still be
absent from RENDERERS -- and then it renders as a <pre> with nothing raising,
nothing logging, the request succeeding and every unit test in the feature
green. CLAUDE.md records the same shape as EntityDefinitionRunner, never
constructed in composition.py, serving empty cache misses past a full suite.

Proved red before green: without the RENDERERS line the block takes the
unknown-fence path and the label lookup fails.

Two assertions rather than one, and both are needed. The section label proves
the type was recognised; the request proves projectId was threaded through to
the widget. A widget rendered without a project satisfies the first and draws a
sentence saying it cannot look anything up.

Nothing in the DTO or mapper layer changed, and that is checked rather than
assumed: a block is an open record on the wire and there is no type allowlist
between the SSE frame and RENDERERS."
```

---

## Self-review

**Spec coverage.**

| Spec section | Task |
| --- | --- |
| §1 one backing read; vocabulary from an unfiltered response | 3 (design + two cost tests), 4 (vocabulary test) |
| §2 a distinct type with its own craft notes | 1 |
| §3 `over` required and `timeline`-only with a warning by name; `vary` not defaulted; `prompt` required | 1 (validation), 2 (reader), 4 (`vary` restricts, prompt renders) |
| §4 commits on release; every parameter set cached; the control produces the accepted format; counts on every result | 3 (cost tests + `type="date"`), 4 (counts) |
| §5 no share affordance, said out loud; `limit` does not bound cost, in craft | 3 (the note), 4 (its test), 1 (craft + two tests) |
| §6 out of scope: graph explorer, unbounded graph `limit`, persistence, topic/source axes | 1 — `EXPLORER_BACKING_READS` and `EXPLORER_AXES` and their docstrings; nothing implements them |
| §7 the four gates plus the fifth; Python registry / `over` / `vary` / projection identity; jsdom controls, prose, counts; browser height; **cost test first** | every task's gate steps; 1; 4; 5; 3 (Task 3 precedes Tasks 4–6) |

**Two spec points that could not be planned as literally written**, both resolved in "Design
decisions this plan locks in" — an executor should read that section before Task 1:

1. §3 wants `over: graph` to be a *validation warning* and §7 wants an unknown `over` to
   *render as prose*. Those are only compatible if `over`'s vocabulary is enforced by the
   `warn` hook rather than by `one_of`: an error routes the block to the error panel and
   leaves no widget to render prose. Task 1 does it that way and
   `test_an_explorer_over_something_unsupported_warns_by_name_and_still_renders` pins it.
2. §1's "one backing read" and §7's "each control changes the query the repository is called
   with" cannot both be literally true when the author fixed an `entity_type`, because a
   filtered response cannot enumerate the types it filtered out. The plan resolves it with two
   queries sharing one key builder — one request in the common case, two on mount when the
   author started filtered, asserted as a number in the cost test rather than left to drift.

**One further honesty, not a spec gap.** The picker's vocabulary is only as complete as an
*uncapped* response: the server caps bands, so a type present only past the cap is not
offered. There is no honest fix without a route that enumerates entity types (§6 says so), and
the widget renders `truncated` on every result partly for that reason. It is written into the
widget's docstring rather than left for someone to discover.

**Placeholder scan.** No `TBD`, no "add appropriate error handling", no "write tests for the
above", no "similar to Task N" — Task 4's and Task 5's fixtures are repeated in full rather
than referenced. One place deliberately says "read the real file rather than trust this plan":
`LessonDocument`'s prop names (Task 6 Step 1). That is a check, not a gap.

**Two claims corrected during this review, both verified against the source rather than
reasoned:** the missing-required note reads `over: required field missing`, not
`over: required` (`components.py:322`); and `frontend/src/domain/lesson/widgets.test.ts`
already exists with its own `block()` helper, so Task 2 appends to it rather than creating it.

**Type consistency.** `readExplorerQuery` / `ExplorerSpec` / `ExplorerAxis` / `varies` /
`EXPLORER_BACKING_READ` are spelled identically in Tasks 2, 3, 4 and 6. `string_subset`,
`EXPLORER_AXES`, `EXPLORER_BACKING_READS` and `_explorer_over` are spelled identically in
Task 1's implementation and both its test files. The DOM contract Task 3 declares
(`[data-explorer-widget]`, `.cmp-explorer-controls`, `.cmp-explorer-prompt`,
`.cmp-explorer-legend`, `.cmp-explorer-field`, `.cmp-explorer-note`, `.cmp-timeline-counts`,
and the labels `Entity type` / `From` / `To`) is exactly what Tasks 4 and 5 query.
`timelines.timeline(projectId, query)` is plural at every mention.
