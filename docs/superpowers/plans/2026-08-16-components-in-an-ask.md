# Components in an Ask — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the ask agent author interactive components, render them live in the ask page, grade them against the stored turn — and teach both agents what a *good* component looks like from one place in the registry.

**Architecture:** `parse_document` is pure and an ask turn is already addressable by `(conversation_id, position)` in the `ask_turns` read model, so the server re-parses the stored answer to recover the answer key exactly as the file surface re-reads a file. The browser is handed the learner projection and cannot mark anything. No progress is recorded — an ask has no principal to key one on.

**Tech Stack:** Python 3.12 / FastAPI / eventsource-py / pydantic; React 19 / TanStack Query / zod / vitest.

**Spec:** `docs/superpowers/specs/2026-08-16-components-in-an-ask-design.md`

## Global Constraints

- Four gates, all four: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`. The ruff pair runs repo-wide, not on touched files.
- **Fifth gate, invisible from `verify`:** any change under `frontend/src` must be followed by `cd frontend && npm run build` and a commit of the rebuilt `research_team/interfaces/web/static/assets/app.js` and `assets/index.css`. `npm run verify` runs the build and never compares it to the committed tree.
- Never run two `vitest` processes at once — concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- Comments explain **why**, not what; they state costs and trade-offs, name what a test would fail on, and say when something was **measured** rather than reasoned. A comment restating the code is worse than none.
- If a test would pass with the change reverted, say so in its docstring. Prove a test red before trusting it green.
- The application layer imports `eventsource` only — no framework. `tests/test_architecture.py` enforces it. LangChain-side work belongs in `infrastructure/agent/`.
- Pre-release: no backwards compatibility is owed. Break shapes rather than migrating, and say so.
- Answer-key rule: `view="learner"` is the only projection that leaves the server toward a reader who is meant to answer. A route that defaults to `author` on a typo is a defect.

---

### Task 1: `craft` guidance in the registry

Teaches both agents what a good item looks like, from the one place that cannot drift from the schemas.

**Files:**
- Modify: `research_team/application/components.py` (`ComponentType` ~line 310; `REGISTRY` ~line 393; `component_reference` ~line 531)
- Test: `tests/application/test_components.py`

**Interfaces:**
- Produces: `ComponentType.craft: tuple[str, ...]` (defaults to `()`), rendered by `component_reference(only=None)` under each type's example.

- [ ] **Step 1: Write the failing test**

In `tests/application/test_components.py`:

```python
def test_the_reference_carries_each_type_s_craft_notes():
    """The generated reference is the only place either agent learns to write
    a good item, so craft travels with syntax or not at all.

    Reverting `craft` to a field nothing renders leaves this red: the strings
    are in the registry either way, and `component_reference` is what has to
    put them in front of a model.
    """
    reference = component_reference(only=["mcq"])

    assert "distractor" in reference
    # The mcq note names per-option feedback, which is the field authors skip.
    assert "feedback" in reference


def test_craft_notes_are_scoped_to_the_types_asked_for():
    """`only` narrows craft the same way it narrows examples -- showing a stage
    how to write a good cloze it was told not to use is the same mistake the
    `only` parameter exists to prevent."""
    reference = component_reference(only=["flashcards"])

    assert "one fact per card" in reference.lower()
    assert "distractor" not in reference
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/application/test_components.py -k craft -v`
Expected: FAIL — `assert "distractor" in reference`.

- [ ] **Step 3: Add the field**

In `components.py`, on `ComponentType` (after `withheld`):

```python
    craft: tuple[str, ...] = ()
    """How to write a *good* one of these, not how to write a valid one.

    Registry-resident for `summary` and `example`'s reason: guidance kept
    beside a schema drifts from it within two edits, and the drift is invisible
    until a model authors faithfully to a description that stopped being true.
    Both the stage prompt and the ask prompt render this, so there is one copy.

    What belongs here is the failure mode this format actually produces -- the
    fourth distractor nobody picks, the blank the sentence gives away -- and
    not a course in assessment design. A model reads this every time it writes
    one; length is a cost paid per authoring turn.
    """
```

- [ ] **Step 4: Fill it in for all four types**

In `REGISTRY`, add to each `ComponentType(...)` call:

```python
    # flashcards
    craft=(
        "One fact per card. A card whose back is a paragraph is a passage that "
        "has been put in the wrong container -- split it or leave it as prose.",
        "Write the front as the question a reader would actually ask "
        "themselves, not as a heading.",
    ),
    # mcq
    craft=(
        "Every distractor should be something a reader who half-understands "
        "would actually pick. An option nobody chooses teaches nothing and "
        "costs a line -- three or four options beat five padded ones.",
        "Give each wrong option `feedback` naming the misunderstanding that "
        "makes it attractive. The moment after a wrong answer is the one "
        "moment the reader is most ready to read why.",
        "`rationale` explains the right answer's reasoning, which is not the "
        "same as restating it.",
    ),
    # cloze
    craft=(
        "Blank the thing being learned, not the word that happens to be a "
        "noun. If the surrounding sentence gives the answer away, the blank "
        "tests reading rather than recall.",
        "Grading normalises case and spacing but not word choice, so use "
        "`{{answer::hint}}` where a term has several defensible spellings.",
        "Three or four blanks in a passage is plenty; a sentence that is more "
        "blank than prose is unreadable rather than difficult.",
    ),
    # checklist
    craft=(
        "Steps someone performs, in the order they perform them -- not facts "
        "they should know. A checklist of facts is a flashcard deck with no "
        "second side.",
        "`note` carries the caveat that would otherwise bloat `text`.",
    ),
```

- [ ] **Step 5: Render it**

In `component_reference`, replace the per-component loop body:

```python
    for component in wanted:
        lines += [f"### {component.name}", "", component.summary, "", component.example, ""]
        if component.craft:
            lines += ["Writing a good one:", ""]
            lines += [f"- {note}" for note in component.craft]
            lines += [""]
```

- [ ] **Step 6: Run the full component suite**

Run: `uv run pytest tests/application/test_components.py -v`
Expected: PASS. If a test asserts an exact reference length or a full-string equality, update it — the reference grew by design.

- [ ] **Step 7: Commit**

```bash
git add research_team/application/components.py tests/application/test_components.py
git commit -m "Teach the registry what a good component looks like

The reference has always carried syntax and an example, and a model handed
those writes the average of its training data: the fourth distractor nobody
picks, the cloze blank the sentence gives away, forty cards on one screen.

In `ComponentType` rather than in the prompt, for the reason `summary` and
`example` are there -- guidance maintained beside a schema drifts from it
within two edits and nothing catches the drift. One copy now reaches both the
stage prompt and (next task) the ask prompt.

Asserted, not measured: that this produces better items. The cost of being
wrong is a longer prompt on stages already carrying the reference."
```

---

### Task 2: The ask agent is told, and one place parses an answer

**Files:**
- Create: `research_team/application/ask_components.py`
- Create: `tests/application/test_ask_components.py`
- Modify: `research_team/infrastructure/agent/ask_agent.py` (`ASK_PROMPT`, ~line 89)
- Test: `tests/infrastructure/test_ask_agent.py` (add to the existing module)

**Interfaces:**
- Consumes: `component_reference(only=...)` from Task 1, now carrying craft notes.
- Produces: `research_team.application.ask_components.answer_document(text: str, view: View = "learner") -> dict[str, Any]` — the projected document for one answer, `{"path": "", "view": ..., "frontmatter": ..., "blocks": [...]}`; and `ASK_COMPONENT_TYPES: tuple[str, ...] = ("mcq", "cloze", "flashcards")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/application/test_ask_components.py`:

```python
from research_team.application.ask_components import ASK_COMPONENT_TYPES, answer_document


def test_an_answer_with_no_components_is_one_markdown_block():
    doc = answer_document("Two papers cover this, both from 1974.")

    assert [block["kind"] for block in doc["blocks"]] == ["markdown"]


def test_a_component_in_an_answer_is_parsed_out_of_the_prose():
    answer = (
        "Here is one to try:\n\n"
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which year?\n"
        "options:\n"
        '  - text: "1974"\n'
        "    correct: true\n"
        '  - text: "1975"\n'
        "    correct: false\n"
        "```\n"
    )

    blocks = answer_document(answer)["blocks"]

    assert [block["kind"] for block in blocks] == ["markdown", "component"]
    assert blocks[1]["type"] == "mcq"


def test_the_learner_view_is_the_default_and_keeps_no_answer():
    """The one assertion that matters on this module. A default of `author`
    would ship the key to the page that is meant not to show it, on every ask.

    Red against `view: View = "author"`."""
    answer = (
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which year?\n"
        "options:\n"
        '  - text: "1974"\n'
        "    correct: true\n"
        '  - text: "1975"\n'
        "    correct: false\n"
        "```\n"
    )

    block = answer_document(answer)["blocks"][0]

    assert "correct" not in str(block["data"])
    assert block["withheld"]


def test_checklist_is_not_offered_to_the_ask_agent():
    """Its only interesting mode is `persist: true`, and the ask path has no
    identity to persist against -- see the design's section 4."""
    assert "checklist" not in ASK_COMPONENT_TYPES
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/application/test_ask_components.py -v`
Expected: FAIL — `ModuleNotFoundError: research_team.application.ask_components`.

- [ ] **Step 3: Write the module**

Create `research_team/application/ask_components.py`:

```python
"""Components inside an ask answer, and the one projection of them.

An ask answer is a string, and `parse_document` takes a string -- so this
module is thin on purpose. It exists so the two surfaces that render an answer
(the live SSE frame and the stored turn) cannot disagree about what a component
in an answer means, and so the learner default is written down once.

**The default view is `learner` here and `author` on a file, and the
asymmetry is deliberate.** The console's file reader is the person building the
course, so showing them their own key is right. Nobody reads an ask answer as
its author -- the model wrote it, and the reader is the one being asked. There
is no caller for whom `author` is the right default, so it is not the default.

What this does *not* claim is that the key is out of reach: the raw answer text
travels beside these blocks (see the route), so withholding here is the
affordance "don't show me the answer until I've tried" rather than a boundary.
The design's section 5 states this at length, and `BACKLOG.md` records it.
"""

from typing import Any

from research_team.application.components import View, parse_document, project

ASK_COMPONENT_TYPES: tuple[str, ...] = ("mcq", "cloze", "flashcards")
"""What the ask agent may author.

`checklist` is absent and that is a ruling, not an omission. A checklist is a
record of a procedure someone performed, and its only interesting mode is
`persist: true` -- which needs a learner identity the ask path deliberately
does not have. A checklist that cannot remember a tick is a list of bullets
with worse affordances than a list of bullets.
"""


def answer_document(text: str, view: View = "learner") -> dict[str, Any]:
    """One ask answer, parsed and projected.

    `path=""` because an answer has no file. `Document.path` is a label used in
    error messages and derived ids -- `derive_id` hashes it with the block's
    index -- so an empty one is stable and honest rather than a fabricated
    filename that would look like something a reader could open.
    """
    return project(parse_document(text, path=""), view=view)
```

- [ ] **Step 4: Run the tests to green**

Run: `uv run pytest tests/application/test_ask_components.py -v`
Expected: PASS, all four.

- [ ] **Step 5: Write the failing prompt test**

In `tests/infrastructure/test_ask_agent.py`:

```python
def test_the_ask_prompt_carries_the_component_reference():
    """Without this the agent never authors one, and every other task in this
    feature renders nothing. Red against the prompt as it stood."""
    from research_team.infrastructure.agent.ask_agent import ASK_PROMPT

    assert "component:mcq" in ASK_PROMPT
    assert "component:checklist" not in ASK_PROMPT
    # Craft, not only syntax -- Task 1's notes reach this prompt through the
    # same generated reference the stage prompt uses.
    assert "distractor" in ASK_PROMPT
```

- [ ] **Step 6: Run it and watch it fail**

Run: `uv run pytest tests/infrastructure/test_ask_agent.py -k prompt -v`
Expected: FAIL — `assert "component:mcq" in ASK_PROMPT`.

- [ ] **Step 7: Extend the prompt**

In `ask_agent.py`, after the existing prompt body and before `+ REFERENCE_SYNTAX_PROMPT`:

```python
ASK_COMPONENT_PROMPT = (
    """
## Asking the reader something back

Some answers land better as something the reader does than as something they
read. You can write an interactive component into an answer and it will render
as a working widget in the page, graded on the server.

**The default is prose, and this is the part to get right.** A component earns
its place when the reader would learn more by *doing* than by reading -- when
they have asked to check their understanding, when they are about to rely on a
distinction the corpus draws finely, or when they asked to be quizzed. A
question about a fact the material states plainly is not worth asking back, and
an answer that ends in a quiz the reader did not want is worse than the same
answer in a paragraph. Most answers should contain no component at all.

Answer the question first. A component is what follows a real answer, never a
substitute for one.

"""
    + component_reference(only=ASK_COMPONENT_TYPES)
)

ASK_PROMPT = (
    """..."""  # unchanged existing body
    + REFERENCE_SYNTAX_PROMPT
    + ASK_COMPONENT_PROMPT
)
```

Add the imports at the top of `ask_agent.py`:

```python
from research_team.application.ask_components import ASK_COMPONENT_TYPES
from research_team.application.components import component_reference
```

- [ ] **Step 8: Run the tests to green**

Run: `uv run pytest tests/infrastructure/test_ask_agent.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add research_team/application/ask_components.py tests/application/test_ask_components.py research_team/infrastructure/agent/ask_agent.py tests/infrastructure/test_ask_agent.py
git commit -m "Let the ask agent write a component, and say when not to

Two thin things. `ask_components.answer_document` is the one place an answer
becomes blocks, so the live frame and the stored turn cannot disagree; its
default view is `learner` where a file's is `author`, because nobody reads an
ask answer as its author.

The prompt gets more words about the occasion than about the syntax. The file
path can assume the occasion -- a stage writing an EVIDENCE_SPEC is writing
assessment items by definition -- and an ask has no such signal. The failure
mode is a model that turns every answer into a quiz, which is what gets a
feature like this switched off in a day.

checklist is excluded: its only interesting mode is persist: true and the ask
path has no identity to persist against."
```

---

### Task 3: The two surfaces return blocks

**Files:**
- Modify: `research_team/interfaces/web/app.py` (`_ask_frame` ~line 2892; `read_ask` ~line 3048)
- Modify: `research_team/application/ask.py` (`AskAnswer` ~line 86; `ask` ~line 238)
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: `answer_document` from Task 2.
- Produces: the `answer` SSE frame gains `blocks: list[dict]` and `position: int`; `read_ask`'s turn views gain `blocks: list[dict]`. `AskAnswer` gains `position: int = 0`.

- [ ] **Step 1: Write the failing tests**

In `tests/interfaces/test_web.py`, beside the existing ask route tests:

```python
def test_the_answer_frame_carries_parsed_blocks_and_its_position(client, ...):
    """The live widget cannot be graded without a position, and cannot be
    rendered without blocks. Red against a frame carrying only `text`."""
    # Arrange an ask whose answer contains one mcq (stub the executor as the
    # neighbouring ask route tests do).
    frames = stream_ask(client, project_id, question="quiz me")

    answer = next(frame for frame in frames if frame["type"] == "answer")
    assert answer["position"] == 0
    assert [block["kind"] for block in answer["blocks"]] == ["component"]
    # The prose survives beside the blocks: a client that ignores `blocks`
    # renders exactly what it rendered before this feature.
    assert answer["text"]


def test_a_stored_turn_is_parsed_the_same_way_as_a_live_one(client, ...):
    """A reader reopening a conversation gets working widgets, not code
    blocks. Red against `read_ask` returning only `answer`."""
    ...
    body = client.get(f"/api/projects/{project_id}/asks/{conversation_id}").json()

    assert [block["kind"] for block in body["turns"][0]["blocks"]] == ["component"]


def test_the_second_turn_s_position_is_one(client, ...):
    """The bug this is written red for is a frame that reports the *count* of
    turns rather than the index of this one -- invisible in every single-turn
    test, and every hand test is a single turn."""
    stream_ask(client, project_id, question="first")
    frames = stream_ask(client, project_id, question="second")

    answer = next(frame for frame in frames if frame["type"] == "answer")
    assert answer["position"] == 1
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/interfaces/test_web.py -k "answer_frame or stored_turn or second_turn" -v`
Expected: FAIL — `KeyError: 'position'`.

- [ ] **Step 3: Carry the position on the answer**

In `application/ask.py`, on `AskAnswer`:

```python
@dataclass(frozen=True)
class AskAnswer:
    text: str
    citations: tuple[Citation, ...] = ()
    #: Which turn of this conversation this answer is, zero-based -- the same
    #: number `AskTurnRow.position` stores, and the half of the grading key the
    #: browser cannot derive. Taken from the registry's message count rather
    #: than by loading the aggregate: two messages are appended per turn, and
    #: the count is read *before* this turn's pair is added.
    position: int = 0
```

In `AskService.ask`, where the answer is yielded (after `_record`, before `yield answer`):

```python
            # Read before `put`, which appends this turn's two messages: the
            # position of *this* answer is the count of completed turns behind
            # it. Reading after would report the next turn's index and nothing
            # in a single-turn test would notice.
            answer = replace(answer, position=len(conversation.messages) // 2)
            await self._record(conversation, question=question, answer=answer)
```

Move the `_record` call to after the `replace` so the recorded and reported positions cannot diverge. `replace` is already imported from `dataclasses`.

- [ ] **Step 4: Return blocks from both surfaces**

In `app.py`, import at the top:

```python
from research_team.application.ask_components import answer_document
```

In `_ask_frame`, the `AskAnswer` branch:

```python
        elif isinstance(note, AskAnswer):
            body = {
                "type": "answer",
                "text": note.text,
                "position": note.position,
                # Parsed here rather than in the browser for the four reasons
                # `application/components.py` opens with, of which the second
                # binds hardest: withholding is only real if the projection
                # happens before the bytes leave. `text` travels beside it
                # anyway (see the design's section 5) -- that is honesty about
                # the strength of the property, not a reason to skip it.
                "blocks": answer_document(note.text)["blocks"],
                "citations": [
                    {"kind": citation.kind, "id": citation.id} for citation in note.citations
                ],
            }
```

In `read_ask`'s turn view, add to each turn dict:

```python
                    "blocks": answer_document(turn.answer)["blocks"],
```

- [ ] **Step 5: Run the tests to green**

Run: `uv run pytest tests/interfaces/test_web.py -k ask -v`
Expected: PASS.

- [ ] **Step 6: Run the ask application suite**

Run: `uv run pytest tests/application/test_ask.py tests/integration/test_ask_writes_nothing.py -v`
Expected: PASS. If an equality assertion on `AskAnswer(...)` fails, it is the new field — update the expected value rather than defaulting the field away.

- [ ] **Step 7: Commit**

```bash
git add research_team/application/ask.py research_team/interfaces/web/app.py tests/
git commit -m "Return an ask answer as blocks as well as prose

Both surfaces, one parse. The live frame gains blocks and a position; the
stored turn gains blocks, so reopening a conversation gives working widgets
rather than code blocks.

`position` is read from the registry's message count before this turn's pair
is appended, which is the index of this answer rather than the count of turns
behind it -- the off-by-one that is invisible in every single-turn test, and
every hand test is a single turn. There is a test for the second turn.

`text` survives beside `blocks`. A client that ignores blocks renders what it
rendered before, which is what makes the frontend half independently
deployable, and it is also the honest position: the key is in the same
response, so this is an affordance and not a boundary."
```

---

### Task 4: Grading an attempt against a stored turn

**Files:**
- Modify: `research_team/interfaces/web/app.py` (add `AskAttempt` beside `Attempt` ~line 501; add the route beside `read_ask` ~line 3048)
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: `ask_turns` via the `asks` read-model accessor (`asks.turns_for(conversation_id)`, rows carrying `position`, `answer`, `project_id`).
- Produces: `POST /api/projects/{project_id}/asks/{conversation_id}/attempts` with body `{position: int, component_id: str, response: Any}` → `Verdict.as_json()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_right_answer_to_an_asked_question_is_marked_correct(client, ...):
    body = client.post(
        f"/api/projects/{project_id}/asks/{conversation_id}/attempts",
        json={"position": 0, "component_id": "q1", "response": 0},
    )

    assert body.status_code == 200
    assert body.json()["correct"] is True


def test_an_attempt_is_graded_against_its_own_turn_not_the_last_one(client, ...):
    """Two turns, each with an mcq whose right answer is a different index.
    A route that read "the conversation's answer" and got the most recent one
    passes every single-turn test and fails this."""
    body = client.post(
        f"/api/projects/{project_id}/asks/{conversation_id}/attempts",
        json={"position": 0, "component_id": "q1", "response": 0},
    ).json()

    assert body["correct"] is True


def test_a_conversation_from_another_project_is_a_404(client, ...):
    """The same ruling `read_ask` already makes: a guessed id and a real one
    belonging to someone else get the same answer."""
    response = client.post(
        f"/api/projects/{other_project_id}/asks/{conversation_id}/attempts",
        json={"position": 0, "component_id": "q1", "response": 0},
    )

    assert response.status_code == 404


def test_an_ungradeable_component_is_a_400_not_a_500(client, ...):
    """A flashcard deck has no right answer. `GradingError` is the client's to
    fix, and every raise site is a 400 or a 404 -- never a 500 on a route a
    reader can reach."""
    response = client.post(
        f"/api/projects/{project_id}/asks/{conversation_id}/attempts",
        json={"position": 0, "component_id": "deck", "response": 0},
    )

    assert response.status_code == 400


def test_grading_works_against_a_conversation_this_process_did_not_stream(client, ...):
    """The arrange phase writes the turn through the projection and never
    calls the ask path, so a route that leaned on the in-memory registry --
    which still holds the conversation in every other test in this file --
    fails here. `CLAUDE.md`'s rule about fixtures that seed through the call
    under test.
    """
    ...
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/interfaces/test_web.py -k "asked_question or own_turn or another_project or ungradeable" -v`
Expected: FAIL — 404 from FastAPI, the route does not exist.

- [ ] **Step 3: Add the request model**

Beside `Attempt` in `app.py`:

```python
class AskAttempt(BaseModel):
    """One reader's answer to a component the model wrote into an answer.

    Addressed by `(position, component_id)` rather than by a file path: an ask
    answer has no file, and the turn is what the server re-parses to recover
    the key. `position` is in the body rather than the path for `Attempt`'s
    reason -- one addressing scheme for both attempt routes beats two.

    No `at`. A file can be revised under a learner, which is what `Attempt.at`
    defends against; an `AskTurnRecorded` is a fact about an answer that was
    given and is never rewritten, so there is no second version to grade
    against.
    """

    position: int
    component_id: str
    response: Any = None
```

- [ ] **Step 4: Add the route**

Beside `read_ask`:

```python
    @app.post("/api/projects/{project_id}/asks/{conversation_id}/attempts")
    async def post_ask_attempt(project_id: UUID, conversation_id: UUID, body: AskAttempt):
        """Mark one attempt at a component the model wrote into an answer.

        The key is recovered by re-parsing the stored answer, which is the same
        move the file surface makes with `session.state.files` -- the browser
        holds the learner projection and could not mark this if it tried.

        **Nothing is recorded.** `LearnerProgress` keys on a session and an ask
        is deliberately not one; the design's section 4 gives the three
        reasons and B33 records the identity question this declines to answer
        by accident. The visible cost is that a refresh blanks the widgets.
        """
        if asks is None:
            raise HTTPException(status_code=503, detail="ask history is not configured")
        row = await asks.get(conversation_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no conversation {conversation_id} in {project_id}"
            )
        turns = await asks.turns_for(conversation_id)
        turn = next((t for t in turns if t.position == body.position), None)
        if turn is None:
            raise HTTPException(
                status_code=404,
                detail=f"conversation {conversation_id} has no turn {body.position}",
            )
        # `author` here, and only here: this is the one caller that needs the
        # key, it is server-side, and nothing it returns carries the block.
        document = parse_document(turn.answer, path="")
        component = document.component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"turn {body.position} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return verdict.as_json()
```

- [ ] **Step 5: Run the tests to green**

Run: `uv run pytest tests/interfaces/test_web.py -k ask -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add research_team/interfaces/web/app.py tests/interfaces/test_web.py
git commit -m "Grade an attempt at a component the model asked back

Re-parses the stored turn to recover the key, which is the file surface's
move with a read model where session.state.files stands. No new grading logic
exists -- grade() takes a ComponentBlock and does not care where it came from.

Records nothing, deliberately: LearnerProgress keys on a session, an ask is
explicitly not one, and B33 already names that as what breaks first under
authentication. Adding a second identity here would answer B33 by accident in
the surface least suited to it. Reversible -- the turn is addressable, so an
attempt aggregate keyed on (conversation_id, position, component_id) can be
added later without changing anything here.

Tested against a turn that is not the last one, and against a conversation
this process never streamed -- the in-memory registry holds every other test's
conversation, which would hide a route that leaned on it."
```

---

### Task 5: The frontend reads blocks off the wire

**Files:**
- Modify: `frontend/src/infrastructure/http/ask-repository.ts` (`askFrameDto` ~line 25, `toEvent` ~line 45)
- Modify: `frontend/src/application/ports/repositories.ts` (`AskEvent`, `AskRepository`)
- Modify: `frontend/src/domain/ask/*` — wherever `AskEvent`'s `answer` variant is declared
- Test: `frontend/src/infrastructure/http/ask-repository.test.ts`

**Interfaces:**
- Consumes: the `answer` frame from Task 3.
- Produces: `AskEvent` `answer` variant gains `blocks: readonly DocumentBlock[]` and `position: number`; `AskRepository.submitAskAttempt(projectId, conversationId, input: {position, componentId, response}) => Promise<Verdict>`.

- [ ] **Step 1: Write the failing test**

In `ask-repository.test.ts`:

```typescript
it('reads blocks and a position off an answer frame', async () => {
  const frame =
    'data: {"type":"answer","text":"try this","position":2,' +
    '"blocks":[{"kind":"component","type":"mcq","id":"q1","data":{},"errors":[],"withheld":["options[].correct"],"gradeable":true}],' +
    '"citations":[]}\n\n'

  const seen = await collect(respond(frame))

  expect(seen[0]).toMatchObject({ type: 'answer', position: 2 })
  expect(seen[0]).toHaveProperty('blocks.0.type', 'mcq')
})

it('defaults blocks and position on a server that sends neither', async () => {
  // Not compatibility -- this build is pre-release. It keeps the parse from
  // rejecting a frame outright during a partial deploy, where the alternative
  // is an answer the reader never sees at all.
  const seen = await collect(respond('data: {"type":"answer","text":"x","citations":[]}\n\n'))

  expect(seen[0]).toMatchObject({ type: 'answer', blocks: [], position: 0 })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/infrastructure/http/ask-repository.test.ts`
Expected: FAIL — `blocks` is not on the parsed event.

- [ ] **Step 3: Widen the DTO**

In `ask-repository.ts`, the `answer` member of `askFrameDto`:

```typescript
  z.object({
    type: z.literal('answer'),
    text: z.string(),
    // `unknown` rather than a block schema: the domain's readers already
    // narrow an open `data` record at the one boundary that needs it (see
    // `domain/lesson/widgets.ts`), and re-deriving the whole component shape
    // in zod would be a second schema to keep in step with the registry.
    blocks: z.array(z.unknown()).default([]),
    position: z.number().int().nonnegative().default(0),
    citations: z.array(citationDto).default([]),
  }),
```

And in `toEvent`:

```typescript
    case 'answer':
      return {
        type: 'answer',
        text: raw.text,
        blocks: raw.blocks as readonly DocumentBlock[],
        position: raw.position,
        citations: raw.citations,
      }
```

- [ ] **Step 4: Widen the port**

In `repositories.ts`, on the `AskEvent` answer variant add `blocks: readonly DocumentBlock[]` and `position: number`; and on `AskRepository`:

```typescript
  /** The browser cannot mark an answer to a question the model asked back
   *  either — the key never left the server. Posts one and renders the reply.
   *
   *  Returns no progress alongside the verdict, unlike the lesson route: an
   *  ask records no attempt, so there is nothing to fold back in. */
  submitAskAttempt(
    projectId: ProjectId,
    conversationId: string,
    input: { position: number; componentId: ComponentId; response: AttemptResponse },
  ): Promise<Verdict>
```

- [ ] **Step 5: Implement it on the repository**

In `HttpAskRepository`, following the class's existing fetch/error conventions (copy the shape from `HttpWorkspaceRepository.submitAttempt`):

```typescript
  async submitAskAttempt(
    projectId: ProjectId,
    conversationId: string,
    input: { position: number; componentId: ComponentId; response: AttemptResponse },
  ): Promise<Verdict> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${projectId.value}/asks/${conversationId}/attempts`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          position: input.position,
          component_id: input.componentId.value,
          response: input.response,
        }),
      },
    )
    // Same verdict shape as the lesson route, so the same parser.
    return verdictDto.parse(await this.json(response))
  }
```

Import `verdictDto` from wherever the lesson repository declares it; if it is private there, lift it to a shared module in this step rather than copying it.

- [ ] **Step 6: Run the tests to green**

Run: `cd frontend && npx vitest run src/infrastructure/http/ask-repository.test.ts`
Expected: PASS.

- [ ] **Step 7: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean. Any fake `AskEvent` in a test or story needs the two new fields.

- [ ] **Step 8: Commit**

```bash
git add frontend/src tests
git commit -m "Read blocks and a position off an ask answer frame

blocks is z.array(z.unknown()) rather than a component schema: the domain's
readers already narrow an open data record at the one boundary that needs it,
and a second schema here would be one more thing to keep in step with the
registry.

Both fields default. Not compatibility -- this build is pre-release -- but a
frame that fails to parse costs the reader the whole answer, and a partial
deploy is exactly when that would happen."
```

---

### Task 6: One attempt state machine, two routes

**Files:**
- Modify: `frontend/src/application/lesson/use-attempts.ts`
- Create: `frontend/src/application/ask/use-ask-attempts.ts`
- Test: `frontend/src/application/ask/use-ask-attempts.test.ts`

**Interfaces:**
- Consumes: `submitAskAttempt` from Task 5.
- Produces: `useAskAttempts(projectId: ProjectId, conversationId: string, position: number): AttemptsApi` — the same `AttemptsApi` `LessonDocument` already takes.

- [ ] **Step 1: Extract the shared machine**

In `use-attempts.ts`, lift the state logic into a non-exported hook taking its two effects as arguments, leaving `useAttempts`'s signature and behaviour untouched:

```typescript
interface AttemptPorts {
  /** What this reader has already done, or null where nothing is recorded.
   *  The ask surface passes null: an ask records no attempt, so there is no
   *  history to fold in and a loader would be a request that always answers
   *  the same empty map. */
  readonly stored: ReadonlyMap<ComponentId, ItemProgress> | null
  submit(block: ComponentBlock, response: AttemptResponse): Promise<Verdict>
  /** Absent where checklists cannot persist. A widget whose save is a no-op
   *  should not offer one, so `Checklist` reads this to decide. */
  saveChecklist?(block: ComponentBlock, checked: readonly number[]): Promise<void>
}

const useAttemptMachine = (documentKey: string, ports: AttemptPorts): AttemptsApi => {
  /* the existing body, with `documentKey` and `ports` in place of the
     sessionId/path/at derivations and the direct `lessons.*` calls */
}
```

- [ ] **Step 2: Run the existing lesson tests**

Run: `cd frontend && npx vitest run src/application/lesson`
Expected: PASS, unchanged. This step is a refactor and the lesson suite is what proves it.

- [ ] **Step 3: Write the failing ask test**

Create `use-ask-attempts.test.ts`:

```typescript
it('posts an attempt against its own turn and renders the verdict', async () => {
  const submitAskAttempt = vi.fn().mockResolvedValue({ correct: true, score: 1, feedback: [] })
  /* render the hook inside a container whose ask repository is the stub */

  await act(() => result.current.submit(block, { kind: 'mcq', chosen: [0] }))

  expect(submitAskAttempt).toHaveBeenCalledWith(projectId, 'conv-1', {
    position: 2,
    componentId: block.id,
    response: { kind: 'mcq', chosen: [0] },
  })
  expect(result.current.stateFor(block).verdict?.correct).toBe(true)
})

it('is a different set of answers for a different turn', () => {
  /** Two widgets in one conversation are two documents. Answers typed against
   *  turn 2 must not appear against turn 3 — the same rule the lesson hook
   *  holds for a changed path, which is why the key is shared. */
})

it('does not offer a checklist save', () => {
  /** Nothing on this path can persist a tick, and a control that silently
   *  drops what it was given is worse than one that is not there. */
  expect(result.current.saveChecklist).toBeUndefined()
})
```

- [ ] **Step 4: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/application/ask/use-ask-attempts.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 5: Write the hook**

```typescript
/** Every widget's state for one ask turn, and the one call that changes it on
 *  the server.
 *
 * Scoped to a turn for the reason the lesson hook is scoped to a file: an
 * answer typed against one question is not an answer to the next, and a stale
 * verdict shown against a different widget would be worse than losing it.
 *
 * `stored` is null and `saveChecklist` is absent, and both are the same fact
 * from two directions: an ask records nothing, so there is no history to
 * restore and no tick to keep. The reader is told this in the page rather than
 * discovering it on refresh. */
export const useAskAttempts = (
  projectId: ProjectId,
  conversationId: string,
  position: number,
): AttemptsApi => {
  const { asks } = useContainer()
  return useAttemptMachine(`${conversationId}:${position}`, {
    stored: null,
    submit: (block, response) =>
      asks.submitAskAttempt(projectId, conversationId, {
        position,
        componentId: block.id,
        response,
      }),
  })
}
```

- [ ] **Step 6: Run both suites to green**

Run: `cd frontend && npx vitest run src/application`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "Share the attempt state machine between a lesson and an ask

The lesson hook's signature and behaviour are unchanged; its body now takes
its two effects as ports. The ask hook passes a null history and no checklist
save, which are the same fact from two directions -- an ask records nothing,
so there is nothing to restore and no tick to keep.

The document-key reset transfers verbatim: a different turn is a different set
of answers, for the reason a different file is."
```

---

### Task 7: The ask page renders widgets

**Files:**
- Modify: `frontend/src/presentation/ask/AskTurn.tsx`
- Test: `frontend/src/presentation/ask/AskTurn.test.tsx`
- Modify: `frontend/src/presentation/ask/AskTurn.stories.tsx`

**Interfaces:**
- Consumes: `useAskAttempts` (Task 6), `LessonDocument` (unchanged), `hasComponents` from `@domain/lesson/document.ts`.

- [ ] **Step 1: Write the failing test**

```typescript
it('renders a widget the model asked back, not a code block', () => {
  render(<AskTurn turn={turnWithMcq} projectId={projectId} conversationId="c1" />)

  expect(screen.getByRole('group', { name: /mcq component/i })).toBeInTheDocument()
  expect(screen.queryByText('component:mcq')).not.toBeInTheDocument()
})

it('keeps the plain markdown path for an answer with no widgets', () => {
  /** The common case grows no second render tree — `hasComponents` is the
   *  same predicate `LessonDocument` uses and exists for this. Red against a
   *  build that routes every turn through the component pipeline. */
})

it('says that an answer here is not remembered', () => {
  /** The one honest difference from a lesson. A reader who does not know this
   *  loses work and blames the page. */
  expect(screen.getByText(/not saved/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/presentation/ask/AskTurn.test.tsx`
Expected: FAIL — no group role; the fence renders as `<pre>`.

- [ ] **Step 3: Branch the renderer**

In `AskTurn.tsx`, replacing the single `<Markdown>` for the answer:

```tsx
  const doc = { blocks: turn.blocks }
  // The same predicate the lesson reader uses, for the same reason: an answer
  // with no widgets keeps the plain path, so the common case grows no second
  // render tree and no attempt state.
  if (!hasComponents(doc)) {
    return <Markdown className="text-fg" source={turn.answer} projectId={projectId} />
  }
  return <AskTurnWidgets doc={doc} projectId={projectId} conversationId={conversationId} position={turn.position} />
```

`AskTurnWidgets` is a sibling component so the hook is not called conditionally:

```tsx
const AskTurnWidgets = ({ doc, projectId, conversationId, position }: ...) => {
  const attempts = useAskAttempts(projectId, conversationId, position)
  return (
    <>
      <LessonDocument doc={doc} attempts={attempts} />
      <p className="ask-widget-note">
        Answers here are not saved — reopening this conversation gives you a blank question.
      </p>
    </>
  )
}
```

- [ ] **Step 4: Wire the withheld wording**

The `cmp-withheld` tooltip in `LessonDocument.tsx` states a property that is true of a file and weaker here (the raw answer travels in the same response). Give the section an optional `withheldExplanation` prop, defaulting to today's text, and pass the ask wording from `AskTurnWidgets`:

```
The answer is not in what this page was given, so it cannot mark your attempt
locally — it asks the server. The full answer is still part of the reply that
carried this question, so this keeps the answer out of sight until you have
tried rather than out of reach.
```

- [ ] **Step 5: Run the tests to green**

Run: `cd frontend && npx vitest run src/presentation/ask`
Expected: PASS.

- [ ] **Step 6: Add a story**

Add an `AskTurn` story with one mcq answer so the widget-in-a-chat-column layout is inspectable. If the story reveals the widget overflowing the chat column, that is a computed-style question — write the assertion in `AskTurn.browser.test.tsx` and run `npm run test:browser`, per `CLAUDE.md`. jsdom cannot judge it.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "Render a component the model asked back

Branches on hasComponents, the same predicate the lesson reader uses: an
answer with no widgets keeps the plain markdown path, so the common case grows
neither a second render tree nor attempt state. LessonDocument is reused
unchanged -- nothing in it names a file, which is what made grading against a
re-parse the right shape in the first place.

The withheld tooltip is parameterised because the file's wording is a lie
here: the raw answer travels in the same response, so this is 'out of sight
until you have tried', not 'out of reach'. B30 one surface further along."
```

---

### Task 8: Backlog, README, console, and all four gates

**Files:**
- Modify: `BACKLOG.md`
- Modify: `README.md`
- Modify: `research_team/interfaces/web/static/assets/app.js`, `assets/index.css` (build output)

- [ ] **Step 1: Record the weakened property**

Add to `BACKLOG.md`'s "Interactive components" section:

```markdown
### B56. Withholding in an ask is weaker than withholding in a file

The ask surface projects the learner view and grades on the server, so the
browser cannot mark an answer -- but the raw answer travels in the *same
response* as the blocks, where B30's subject at least needed a second request
to a different route.

Taken deliberately. Stripping the prose would mean reconstructing the answer
from blocks in a client, which is a second renderer and a new class of bug, to
defend against a reader who wants the answer to a question they asked for
themselves. On a course file the author and the learner are two people; on an
ask they are one.

The UI says so in its own words rather than reusing the file's tooltip, which
would be dishonest here. Closes with B18 alongside B30, or sooner if an ask
ever grows a second reader.
```

- [ ] **Step 2: Document the feature**

In `README.md`, beside the existing components section, three or four sentences: the ask agent may write mcq, cloze and flashcards into an answer; they render and grade live; **nothing is recorded**, so a refresh blanks them; and the withholding on that surface is the affordance described in B56.

- [ ] **Step 3: Rebuild the console**

Run: `cd frontend && npm run build`
Then: `git status` — `research_team/interfaces/web/static/assets/*` must show as modified. If it does not, the build did not run against this tree.

- [ ] **Step 4: Run all four gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

All four must pass. `verify` covers no Python; `pytest` covers no formatting; the ruff pair runs repo-wide.

- [ ] **Step 5: Take the one measurement the spec promised**

Generate one evidence-spec artifact through a stage that carries the component reference, before and after Task 1's craft notes (`git stash` the registry change or read a pre-change generation). Record in the commit message what actually differed — number of distractors, whether per-option feedback appeared, whether cloze blanks fell on content words. **If nothing improved, say that.** The spec asserts this and does not measure it; one observation beats none, and a negative one is worth more than silence.

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "Document components in an ask, and rebuild the console

B56 records the withholding property this surface actually has, which is
weaker than a file's and weaker than B30's subject: the key is in the same
response rather than a route away.

Measured [before/after craft guidance]: <the observation from step 5>."
git push -u origin worktree-ask-components
```

- [ ] **Step 7: Open the PR**

Body: what this builds, the four rulings from the spec's commit (no progress recorded, weaker withholding, no checklist, craft in the registry), and the measurement from step 5 stated plainly whichever way it came out.

---

## Self-Review

**Spec coverage:** §1 → Task 2; §2 → Tasks 2–3; §3 → Task 4; §4 → Task 4 (route records nothing) + Task 6 (`stored: null`); §5 → Task 7 step 4 + Task 8 step 1; §6 → Tasks 5–7; §7 → Task 1. Testing section → the named tests in Tasks 3, 4, 6, 7 plus Task 8's gates.

**One gap accepted:** the spec's "property test that no answer survives the ask projection" is not its own task. `answer_document` delegates to `project`, which already carries that property test for files, and a second generator over the same function would test `project` twice. Task 2's `test_the_learner_view_is_the_default_and_keeps_no_answer` covers the part that is actually new here — the default. Recorded rather than silently dropped.

**Type consistency:** `answer_document(text, view)` (Task 2) is called with one argument in Task 3 and its `["blocks"]` used in both surfaces; `AskAttempt{position, component_id, response}` (Task 4) matches `submitAskAttempt`'s body (Task 5) and `useAskAttempts`'s call (Task 6); `AttemptsApi` is unchanged throughout, which is what lets Task 7 reuse `LessonDocument`.
