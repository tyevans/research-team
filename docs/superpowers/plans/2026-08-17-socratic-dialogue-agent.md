# Socratic Dialogue — Plan 2 of 3: the agent and the live surface

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the dialogue a model behind it and an HTTP surface in front of it — a prompted socratic executor, the POST route and its SSE stream, and `mcq`/`cloze` attempts recorded against the dialogue id — so a dialogue can be held end to end with `curl`.

**Architecture:** `DeepAgentSocraticExecutor` reuses the ask executor's plumbing (`create_deep_agent`, `readable`, `ReadOnlyProjectBackend`, `READ_ONLY_FILE_TOOLS`, the activity translation) behind Plan 1's `SocraticExecutor` Protocol. Its prompt is **composed from pieces**, never concatenated onto `ASK_PROMPT`. The route pair mirrors the ask's POST-and-stream shape over `SocraticDialogueService.respond`, and the attempts route writes twice: a `LearnerProgress` attempt keyed on the dialogue id, and a `SocraticProgressObserved` with `evidence="attempt"` so a graded answer is evidence toward the stopping condition.

**Tech Stack:** Python 3 / deepagents + LangChain (infrastructure layer only) / FastAPI + `StreamingResponse` / pydantic / `eventsource-py`.

**Spec:** `docs/superpowers/specs/2026-08-17-socratic-dialogue-design.md`

**Predecessor:** `docs/superpowers/plans/2026-08-17-socratic-dialogue.md` (Plan 1). Its Tasks 1–4 have landed — `36b5a70` is the composition commit and the gate this plan waited on. **Its Task 5 (the read-only history routes) runs next, before any task in this plan.**

## What this plan does NOT do, and why you must not read it as finishing the feature

**After Plan 2, a dialogue still cannot end.** `SocraticDialogueConcluded` is
written by nothing in Plans 1 or 2, and neither is any
`SocraticProgressObserved` with `evidence="assessment"` — both need the model to
return structured judgement alongside its prose, which is a second parse whose
failure mode is *silent*: a malformed answer means "not concluded" rather than
raising. That belongs in its own slice with its own red proofs, and it is
**Plan 4, "concluding a dialogue"**, planned after Plan 3.

**Why it is a fourth plan rather than folded into this one or merged into Plan
3.** It is agent judgement, and Plan 3 is a frontend slice — merging them puts a
parser and a stylesheet under one review pass. And a parse that fails silently
is exactly the kind of thing that needs its own red proofs rather than riding
along at the end of another plan, where a green suite would mean only that
nothing raised.

Why this matters more than a missing field: the spec's opening sentence is that
a socratic dialogue "stops when the reader has demonstrated the thing — not when
the reader stops typing". Until Plan 4, it stops when the reader stops typing.
**A dialogue that can only end by being abandoned is the ask with a different
prompt.** Plans 1–3 are still worth shipping in that state — a durable,
resumable, gradeable, goal-visible dialogue is real — but nobody reading these
plans should conclude the feature is done.

The concrete consequence for anyone working in this code: **the `concluded`
terminal status Plan 1 built into `SocraticDialogueState` and
`SocraticDialogueRow` is unreachable in practice**, and its refusal branches in
`decide` are covered only by unit tests that construct the state directly. It is
not dead code. Task 3 puts a comment saying so at the one place a reader will be
standing when they wonder.

---

## What Plan 1 actually left you

Read this before Task 1. It is checked against the landed code, not against Plan 1's text — four tasks shifted in flight.

**The seam is exactly five lines.** `grep _UnbuiltSocraticExecutor` finds them all, all in `composition.py`:

| Line | What it is |
| --- | --- |
| 473 | `Application.socratic`'s docstring, saying the executor is a placeholder |
| 901 | the `class _UnbuiltSocraticExecutor` definition |
| 910 | its "delete this class in Plan 2" note |
| 1998 | the comment above `socratic_service = SocraticDialogueService(...)` |
| 2007 | `executor=_UnbuiltSocraticExecutor()` |

Task 3 of this plan replaces all five. Nothing else in the repository names it.

**What exists and must not be re-derived:**

- `research_team/domain/socratic_dialogue.py` — four events, four commands,
  `SocraticDialogueState`, terminal `concluded` status. A turn is
  `RecordSocraticTurn(dialogue_id, reply, prompt, citations)` — reader's answer
  first, dialogue's response second.
- `research_team/application/socratic.py` — `DialogueMessage`, `SocraticFraming`,
  `SocraticObservation`, `SocraticPrompt`, `SocraticDialogueOpened`, `SocraticNote`,
  `UnknownDialogue`, `DialogueInFlight`, `LiveDialogue`, `DialogueRegistry`,
  `SocraticExecutor` (the Protocol this plan implements), `DialogueReadModel`,
  `SocraticDialogueService` with `begin`, `respond`, `forget`.
- `research_team/infrastructure/persistence/read_models.py` — `SocraticDialogueRow`,
  `SocraticTurnRow`, `SocraticDialogueStore`, `SocraticDialogueProjection`,
  `SocraticDialogueRunner`.
- `composition.py` — `Application.socratic` and `Application.dialogues`, both
  constructed and started.
- `tests/integration/test_a_dialogue_survives_a_restart.py` — passing.

**What does NOT exist yet, and is not this plan's job:** Plan 1's Task 5, the
read-only history routes (`GET /dialogues`, `GET /dialogues/{id}`). There are no
dialogue routes in `app.py` at all. **Task 4 of this plan adds `socratic` to
`create_app` and Plan 1's Task 5 will add `dialogues`** — two parameters, two
tasks, no collision, but whoever runs them second must not delete the other's
line from `web.py`. Both are named in Task 4's Wiring step.

## Global Constraints

Every task's requirements implicitly include this section.

- **Four gates, and passing three is not passing.** `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`.
  The two ruff commands run over the whole repository.
- **No task in this plan touches `frontend/src`.** If one ends up doing so, the
  fifth gate applies: `cd frontend && npm run build` and commit the rebuilt
  `research_team/interfaces/web/static` assets, because CI compares them and
  `verify` never does. Task 5's last step checks that tree is clean.
- **Do NOT build the socratic prompt by concatenating onto `ASK_PROMPT`.**
  `ask_agent.py:142` rebinds `ASK_PROMPT = ASK_PROMPT + ASK_COMPONENT_PROMPT`,
  and that component reference now covers nine types — measured at 9,600
  characters. Appending inherits all six resolved types silently, including five
  that cannot resolve without a project the dialogue surface does have but has
  never been designed around. **Compose from the pieces.**
- **Which components a dialogue may author is a decision, not an inheritance.**
  `mcq` and `cloze` only in the first release: they are gradeable, and grading is
  what feeds the stopping condition. This is the same defect `COMPONENTS_FOR` was
  fixed to avoid — a registry entry joining a prompt by existing.
- **Never default an optional collaborator with `or`.** Use
  `x if x is not None else fallback`. Plan 1 was bitten twice by a falsy empty
  collection substituting an object the code under test never saw; once it made
  a test incapable of failing. `DialogueRegistry.__bool__` exists because of it.
- **An event no projection handles counts as APPLIED, not rejected.** Every
  assertion about persistence must be that a **row or event exists with the value
  it carried** — never that a request returned 200. A missing subscription is a
  silently empty 200 with nothing raising anywhere.
- **`SocraticDialogueService._record` loads and never creates**, and that is a
  second line of defence, not an accident. See "Rulings" below before touching it.
- **The application layer may not import a framework.** `tests/test_architecture.py`
  holds it to `eventsource` alone. Everything LangChain-shaped in this plan lives
  in `research_team/infrastructure/agent/`.

---

## Rulings this plan makes, and why

**`_record` must not gain `AskService._record`'s `create_new` fallback.** It is
the obvious edit for anyone reusing the neighbour, and it removes a measured
protection: because `_record` loads, an id `_resume` fabricated or got wrong dies
at the repository with `AggregateNotFoundError` rather than quietly opening a
second stream. Plan 1 measured this on 2026-08-17 — a sabotage returning a fresh
`uuid4()` from `_resume` raised there and never reached an assertion; adding the
fallback let it through and failed
`test_an_evicted_dialogue_resumes_on_the_same_stream`'s stream-identity check
with the fabricated id as an extra entry. Nothing in this plan needs the
fallback: `begin` is still the only thing that starts a stream.

**`SocraticPrompt.position` is `len(messages) // 2`, and this plan is where a
reader can see it be wrong.** Plan 1 shipped `(len - 1) // 2` for a commit on
the reasoning that a dialogue's history carries a leading opening question the
ask's does not. The reasoning is right and the arithmetic is not: with the
opening question present the history length is odd and both formulas agree, and
they differ **only on even lengths** — which happen when `_resume` finds an empty
`opening_prompt`, a case `SocraticDialogueStarted` permits and older streams
therefore produce. Task 5 makes `position` half the grading key
(`path=f"turn/{position}"`), so on such a dialogue the wrong formula collides two
exchanges onto one key: the reader answers the `mcq` in exchange 2 and the server
marks it against exchange 1's component, or answers 404. Task 5's tests cover
both parities for that reason, and the odd case alone cannot tell the formulas
apart.

**Attempts write twice, and the second write is the point.** A graded answer is
recorded as a `LearnerProgress` attempt keyed on the **dialogue id** (spec §3),
*and* as a `SocraticProgressObserved` with `evidence="attempt"` on the dialogue's
own stream. Without the second, grading in a dialogue is exactly grading in an
ask — a verdict shown and forgotten — and the spec's whole argument for answering
B33 here is that "a socratic dialogue that asks an `mcq` and records the attempt
can use the answer as evidence toward its stopping condition". `EvidenceKind`
already distinguishes `"attempt"` from `"assessment"` so a stopping condition met
entirely by the model's own opinions stays visible as such.

**`path` on a dialogue attempt is `f"turn/{position}"`.** `LearnerProgress.decide`
rejects an empty path ("an attempt needs a path and a component id"), and a
dialogue has no file. The progress id is already the dialogue, so what `path`
must disambiguate is *which exchange's* component — which is the position. A bare
`str(position)` would work and reads as a magic number in a column that holds
file paths everywhere else.

---

## File structure

| File | Responsibility |
| --- | --- |
| `research_team/application/socratic_components.py` | `SOCRATIC_COMPONENT_TYPES`, and the one projection of a dialogue's prompt |
| `tests/application/test_socratic_components.py` | that the tuple is a decision and reaches the prompt |
| `research_team/infrastructure/agent/socratic_agent.py` | `SOCRATIC_PROMPT` composed from pieces, `DeepAgentSocraticExecutor` |
| `tests/infrastructure/test_socratic_agent.py` | prompt composition, framing parse, reply parse, activity contract |
| `research_team/composition.py` | the real executor replaces `_UnbuiltSocraticExecutor`; `progress` reaches the service |
| `tests/integration/test_a_dialogue_is_composed_with_a_model.py` | the composed executor, over a fake model |
| `research_team/interfaces/web/app.py` | `socratic=` parameter, `POST /dialogues`, `POST /dialogues/{id}/reply`, `_socratic_frame`, the attempts route |
| `web.py` | passes `socratic=application.socratic` |
| `tests/integration/test_socratic_stream.py` | the two POST routes and their frames |
| `tests/integration/test_socratic_attempts.py` | grading, both writes, and the position-parity cases |

---

### Task 1: What a dialogue may author

**Files:**
- Create: `research_team/application/socratic_components.py`
- Create: `tests/application/test_socratic_components.py`

**Interfaces:**
- Consumes: `component_reference(only: Iterable[str] | None = None) -> str` and
  `parse_document`, `project`, `View` from `research_team.application.components`.
- Produces:

```python
SOCRATIC_COMPONENT_TYPES: tuple[str, ...] = ("mcq", "cloze")

def dialogue_document(text: str, view: View = "learner") -> dict[str, Any]: ...
```

  `dialogue_document` is the dialogue's equivalent of `ask_components.answer_document`
  — `parse_document(text, path="")` then `project(..., view=view)`, learner by
  default. Task 4's SSE frame and Task 5's attempts route both call it.

- [ ] **Step 1: Write the failing tests**

Create `tests/application/test_socratic_components.py`:

```python
"""What a dialogue may author, and the one projection of it.

The tuple is written out rather than derived, for `ASK_COMPONENT_TYPES`'
reason: a derived list is how `COMPONENTS_FOR[BUILD]` came to advertise five
widgets that cannot work where its prompt is used -- a registry entry joined a
prompt by existing. A third type here should be a decision somebody made.
"""

from research_team.application.socratic_components import (
    SOCRATIC_COMPONENT_TYPES,
    dialogue_document,
)


def test_only_gradeable_components_are_offered():
    """`mcq` and `cloze`, and the reason is the stopping condition.

    Grading is what feeds it (design §3): a dialogue that asks an item and
    marks the answer has *evidence* the reader demonstrated something, where a
    dialogue that asks for prose has only the model's opinion of it.
    `flashcards` is gradeable in the registry's sense but has no verdict to
    feed anything -- nothing is right about a card.

    The five resolved types are absent for a second reason, and it is not the
    ask's: they would resolve here, because a dialogue *has* a project in
    scope. They are out because nothing in a dialogue yet uses what they draw,
    and offering a model six ways to answer with a picture when the surface is
    about questioning is how a socratic dialogue becomes a slideshow. This is
    the entry to revisit first when the surface grows.
    """
    assert SOCRATIC_COMPONENT_TYPES == ("mcq", "cloze")


def test_a_component_in_a_prompt_is_parsed_out_of_the_prose():
    text = (
        "Before we go on, try this:\n\n"
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which council?\n"
        "options:\n"
        '  - text: "Nicaea"\n'
        "    correct: true\n"
        '  - text: "Chalcedon"\n'
        "    correct: false\n"
        "```\n"
    )

    blocks = dialogue_document(text)["blocks"]

    assert [block["kind"] for block in blocks] == ["markdown", "component"]
    assert blocks[1]["type"] == "mcq"


def test_the_learner_view_is_the_default_and_keeps_no_answer():
    """The one assertion that matters on this module, and it matters more here
    than on the ask: a dialogue's whole method is asking rather than telling,
    so a default of `author` would hand the reader the key on the exact frame
    that was meant to make them think.

    Red against `view: View = "author"`.
    """
    text = (
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which council?\n"
        "options:\n"
        '  - text: "Nicaea"\n'
        "    correct: true\n"
        '  - text: "Chalcedon"\n'
        "    correct: false\n"
        "```\n"
    )

    block = dialogue_document(text)["blocks"][0]

    assert "correct" not in str(block["data"])
    assert block["withheld"]


def test_a_dialogue_offers_no_component_the_ask_withholds_nothing_for():
    """Every offered type must actually have a key to withhold, because the
    withholding is what makes asking one worth more than asking in prose.

    Red against adding `flashcards` or any resolved type to the tuple: both
    project to identity, so the assertion below finds an empty `withheld`.
    """
    from research_team.application.components import REGISTRY

    for name in SOCRATIC_COMPONENT_TYPES:
        component = REGISTRY[name]
        assert component.gradeable, f"{name} is offered but cannot be marked"
        assert not component.resolved, f"{name} is a reference, not a question"


def test_the_prompt_a_socratic_agent_receives_carries_every_offered_type():
    """The end of the wiring, and the only assertion here that touches what a
    real dialogue turn is handed.

    Widening the tuple buys nothing if the call site renders a hardcoded list
    instead -- the drift `only=` exists to prevent, and which no other test in
    this file would catch because every one of them reads the tuple rather than
    the prompt built from it.
    """
    from research_team.infrastructure.agent.socratic_agent import SOCRATIC_PROMPT

    for name in SOCRATIC_COMPONENT_TYPES:
        assert f"component:{name}" in SOCRATIC_PROMPT, f"{name} never reaches the model"


def test_the_socratic_prompt_inherits_nothing_from_the_ask_s_component_reference():
    """The trap the design names by measurement.

    `ask_agent.py:142` rebinds `ASK_PROMPT = ASK_PROMPT + ASK_COMPONENT_PROMPT`,
    and that reference now covers nine types at 9,600 characters. A socratic
    prompt built by appending to `ASK_PROMPT` inherits all six resolved types
    silently -- it still *works*, which is why nothing else would catch it, and
    it teaches the model to answer with pictures on a surface whose method is
    questioning.

    Red against `SOCRATIC_PROMPT = ASK_PROMPT + "..."`.
    """
    from research_team.infrastructure.agent.socratic_agent import SOCRATIC_PROMPT

    for unwanted in ("definition", "evidence", "graph", "timeline", "compare", "explorer"):
        assert f"component:{unwanted}" not in SOCRATIC_PROMPT, (
            f"{unwanted} reached the socratic prompt, which means it was built by "
            f"appending to ASK_PROMPT rather than composed from pieces"
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/application/test_socratic_components.py -x`

Expected: FAIL — `ModuleNotFoundError: No module named
'research_team.application.socratic_components'`.

The last two tests import `socratic_agent`, which Task 2 creates; they will keep
failing after this task and that is expected. **Note which two**, so Task 2's
step 6 can confirm they turned green for the right reason.

- [ ] **Step 3: Write the module**

Create `research_team/application/socratic_components.py`:

```python
"""Components inside a dialogue's question, and the one projection of them.

The sibling of `ask_components.py`, and thin for the same reason: a dialogue's
question is a string and `parse_document` takes a string. It exists so that the
surfaces which render a dialogue -- the live SSE frame and the stored turn --
cannot disagree about what a component in a question means.

**The default view is `learner`, and here that is not a close call.** A
dialogue's whole method is asking rather than telling; shipping the answer key
on the frame that was meant to make the reader think would defeat the surface
rather than merely leak from it. `ask_components.py` argues the same default at
length and the argument only gets stronger here.
"""

from typing import Any

from research_team.application.components import View, parse_document, project

SOCRATIC_COMPONENT_TYPES: tuple[str, ...] = ("mcq", "cloze")
"""What a socratic dialogue may author.

Two types, and the list is a ruling rather than an inheritance -- the same
defect `COMPONENTS_FOR[BUILD]` was fixed to avoid, where a registry entry joined
a prompt by existing.

**Gradeable only, because grading is what feeds the stopping condition.** A
dialogue that asks an `mcq` and marks the answer has evidence that the reader
demonstrated something (`EvidenceKind.attempt`); a dialogue that asks for prose
has the model's opinion of it (`EvidenceKind.assessment`). A stopping condition
met entirely by the second is a dialogue that graded its own homework, and these
two types are the only way this build can produce the first.

`flashcards` is out despite being in the ask's list: it has no verdict, so
nothing about it can be evidence of anything.

The five resolved types are out for a *different* reason than the ask's, and the
difference is worth stating because the obvious argument does not apply. They
would resolve perfectly well here -- a dialogue has a project in scope where a
course file does not. They are out because nothing in a dialogue yet uses what
they draw, and offering a model six ways to answer with a picture, on a surface
whose entire method is questioning, is how this becomes a slideshow. Revisit
this entry first when the surface grows; `explorer` in particular is a plausible
second release, since inviting a reader to look is close to what a dialogue is
already doing.
"""


def dialogue_document(text: str, view: View = "learner") -> dict[str, Any]:
    """One dialogue utterance, parsed and projected.

    `path=""` because a dialogue has no file -- `Document.path` is a label used
    in error messages and derived ids, so an empty one is stable and honest
    rather than a fabricated filename a reader could try to open. Identical to
    `answer_document` in body, and deliberately not shared with it: the two
    surfaces will not keep the same default forever, and a shared helper is
    where that divergence becomes a change to both.
    """
    return project(parse_document(text, path=""), view=view)
```

- [ ] **Step 4: Run the tests that do not need Task 2**

Run: `uv run pytest tests/application/test_socratic_components.py -x -k "not prompt_a_socratic_agent and not inherits_nothing"`

Expected: PASS, 4 tests.

- [ ] **Step 5: Wiring**

Nothing constructs this yet — Task 2 is its first reader, and Tasks 4 and 5 are
the second and third. What to confirm now is the *upstream* half:

Run: `uv run python -c "from research_team.application.components import REGISTRY; print([(n, REGISTRY[n].gradeable, REGISTRY[n].resolved) for n in ('mcq','cloze')])"`

Expected: both `gradeable=True, resolved=False`. If either flag has moved, the
fourth test above is what fails and the tuple needs re-deciding, not patching.

- [ ] **Step 6: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest` (the two `socratic_agent` tests are expected red; every other
  test in the repository must pass)

- [ ] **Step 7: Commit**

```bash
git add research_team/application/socratic_components.py \
  tests/application/test_socratic_components.py
git commit -m "Decide what a dialogue may author: mcq and cloze

Two types, written out rather than derived. A derived list is how
COMPONENTS_FOR[BUILD] came to advertise five widgets that could not work where
its prompt was used -- a registry entry joined a prompt by existing -- and a
third type here should be a decision somebody made.

Gradeable only, because grading is what feeds the stopping condition. An mcq
the reader answers produces evidence; prose the model approves of produces the
model's opinion, and a stopping condition met entirely by the second is a
dialogue that graded its own homework. flashcards is gradeable in the
registry's sense and has no verdict, so it is out too.

The five resolved types are out for a different reason than they are out of the
course prompt, and the difference is worth writing down because the obvious
argument does not apply here: they WOULD resolve, since a dialogue has a
project in scope. They are out because nothing in a dialogue uses what they
draw yet, and six ways to answer with a picture on a surface whose method is
questioning is how this becomes a slideshow.

Two tests in this commit are red: they assert against SOCRATIC_PROMPT, which
the next commit builds. They are here rather than there because they are
claims about this tuple -- that it reaches the model, and that nothing else
did."
```

---

### Task 2: The socratic prompt, composed from pieces

**Files:**
- Create: `research_team/infrastructure/agent/socratic_agent.py` (prompt only in
  this task; the executor lands in Task 3)
- Create: `tests/infrastructure/test_socratic_agent.py`

**Interfaces:**
- Consumes: `component_reference`, `SOCRATIC_COMPONENT_TYPES`,
  `REFERENCE_SYNTAX_PROMPT` (`research_team.application.corpus_read`).
- Produces:

```python
SOCRATIC_TOOLS_PROMPT: str      # the shared "you can read, you cannot write" half
SOCRATIC_METHOD_PROMPT: str     # how to conduct a dialogue
SOCRATIC_FRAMING_PROMPT: str    # how to turn a topic into goal + condition + opening
SOCRATIC_COMPONENT_PROMPT: str  # when to ask with a component, + the reference
SOCRATIC_PROMPT: str            # the reply-turn prompt
SOCRATIC_FRAMING_SYSTEM: str    # the framing-turn prompt
```

  Two assembled prompts, not one: `frame` and `respond` are different calls
  wanting different instructions, and Task 3's executor uses one for each.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_socratic_agent.py`:

```python
"""The socratic agent: what it is told, and what it does with what comes back.

The prompt assertions are structural rather than about wording -- a test that
pinned sentences would fail on every improvement to the prompt and teach people
to delete it. What is pinned is what the design's §4 says must not drift: that
the prompt is composed rather than appended, that the component reference is
the two-type one, and that the two calls get different instructions.
"""

from research_team.application.socratic_components import SOCRATIC_COMPONENT_TYPES
from research_team.infrastructure.agent.socratic_agent import (
    SOCRATIC_COMPONENT_PROMPT,
    SOCRATIC_FRAMING_SYSTEM,
    SOCRATIC_PROMPT,
    SOCRATIC_TOOLS_PROMPT,
)


def test_the_reply_prompt_is_built_from_the_pieces_and_not_from_the_ask_s():
    """The design's §4 trap, asserted on identity rather than on wording.

    `ASK_PROMPT` is rebound at `ask_agent.py:142` to carry the whole nine-type
    component reference -- 9,600 characters -- so a socratic prompt built by
    appending to it inherits six resolved types silently and still works.

    Red against `SOCRATIC_PROMPT = ASK_PROMPT + SOCRATIC_METHOD_PROMPT`: the
    ask's own opening sentence arrives with it.
    """
    from research_team.infrastructure.agent.ask_agent import ASK_PROMPT

    assert SOCRATIC_TOOLS_PROMPT in SOCRATIC_PROMPT
    assert SOCRATIC_COMPONENT_PROMPT in SOCRATIC_PROMPT
    assert ASK_PROMPT not in SOCRATIC_PROMPT
    # The ask's first line, which no composed prompt would contain.
    assert "You are answering questions about" not in SOCRATIC_PROMPT


def test_the_component_reference_carries_exactly_the_two_offered_types():
    for name in SOCRATIC_COMPONENT_TYPES:
        assert f"component:{name}" in SOCRATIC_COMPONENT_PROMPT
    for unwanted in ("flashcards", "checklist", "definition", "graph", "explorer"):
        assert f"component:{unwanted}" not in SOCRATIC_COMPONENT_PROMPT


def test_the_framing_call_and_the_reply_call_are_told_different_things():
    """Two prompts because they are two jobs. The framing call turns a topic
    into a goal, a stopping condition and an opening question, once; the reply
    call is handed that framing and continues toward it.

    Red against a single prompt used for both, which would ask the model to
    re-decide the goal on every exchange -- and a goal the model can re-decide
    is not a stopping condition anything can test.
    """
    assert SOCRATIC_FRAMING_SYSTEM != SOCRATIC_PROMPT
    # The framing call must not be offered components: it produces three
    # strings, not an utterance to the reader.
    assert "component:mcq" not in SOCRATIC_FRAMING_SYSTEM
    # And both share the tools half, because both may read the corpus.
    assert SOCRATIC_TOOLS_PROMPT in SOCRATIC_FRAMING_SYSTEM


def test_the_reply_prompt_says_the_reader_cannot_be_told_the_answer():
    """The one instruction that makes this surface different from an ask, and
    the one a model will drift from first. Structural: the prompt has to say
    something about not answering, because a socratic agent that answers is an
    ask agent with extra steps."""
    lowered = SOCRATIC_PROMPT.lower()

    assert "question" in lowered
    assert any(word in lowered for word in ("do not answer", "rather than answering", "not to answer"))


def test_the_reply_prompt_tells_the_model_the_stopping_condition_is_not_its_to_move():
    """The stopping condition is decided once, at framing, and lives in the
    aggregate. A model invited to revise it mid-dialogue produces a dialogue
    that stops when the model gets bored, which is what having a testable
    stopping condition was for."""
    lowered = SOCRATIC_PROMPT.lower()

    assert "stopping condition" in lowered
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/infrastructure/test_socratic_agent.py -x`

Expected: FAIL — `ModuleNotFoundError: No module named
'research_team.infrastructure.agent.socratic_agent'`.

- [ ] **Step 3: Write the prompt module**

Create `research_team/infrastructure/agent/socratic_agent.py` with the prompt
pieces. The executor is Task 3; write only the strings here.

```python
"""A deep agent that leads a reader by questioning, and changes nothing.

The executor behind `SocraticDialogueService`. It reuses the ask executor's
plumbing wholesale -- the same read-only tool set, the same file backend, the
same activity translation -- and differs in exactly one thing that matters: what
it is told to do with them.

**The prompt is composed from pieces and never appended to `ASK_PROMPT`.**
`ask_agent.py:142` rebinds `ASK_PROMPT` to include its component reference,
which now covers nine types at 9,600 characters. Appending would inherit six
resolved types silently -- and it would *work*, which is why nothing but
`test_the_reply_prompt_is_built_from_the_pieces_and_not_from_the_ask_s` would
catch it. What it would cost is the surface: a model handed six ways to answer
with a drawing, on a page whose whole method is asking, writes a slideshow.

**Two assembled prompts, because there are two calls.** `frame` runs once and
turns a topic into a goal, a stopping condition and an opening question;
`respond` runs per exchange and is handed that framing. One prompt for both
would invite the model to re-decide the goal every turn, and a goal the model
can revise is not a stopping condition anything can test.
"""

from research_team.application.corpus_read import REFERENCE_SYNTAX_PROMPT
from research_team.application.components import component_reference
from research_team.application.socratic_components import SOCRATIC_COMPONENT_TYPES

SOCRATIC_TOOLS_PROMPT = (
    """You can read one research project's gathered material and change none of it.

You have its sources, its knowledge graph, its topics and its files. You have no
access to the web. The sources are mounted read-only at `/sources/<source_id>`,
so `grep` searches all of them at once. Open one with `read_source`, not
`read_file`: only `read_source` returns the `source_id@start-end` span that makes
a quote checkable.

If the material does not cover something, say so plainly rather than filling the
gap from memory. A dialogue that invents its ground is worse than one that stops.

"""
    + REFERENCE_SYNTAX_PROMPT
)
"""The half both calls share. Deliberately the same claims the ask agent makes
about the same tools -- the tool set is identical and a second, drifting
description of it would be a second thing to keep true."""

SOCRATIC_METHOD_PROMPT = """
## How to conduct this

You are leading a reader toward understanding something, by questioning. You are
not answering their questions -- that is a different surface, and a reader who
wanted answers is on it.

Every turn, you are given the goal, the stopping condition, and the conversation
so far. You reply with **one question**.

What makes a good one:

- It follows from what the reader just said. A question that ignores their answer
  tells them the conversation is a form to fill in.
- It is answerable from what they already know or can work out. A question that
  needs a fact they have not met is a quiz, and they will guess.
- It narrows. If their answer was vague, ask for the part that would make it
  precise; if it was precise and wrong, ask about the thing that makes it wrong.
- One question, not three. Three questions get one answer, usually to the
  easiest.

When the reader says something that meets the stopping condition, say so, say
what they demonstrated, and stop. Do not ask one more to be sure -- the stopping
condition is the thing that decides, and it was written down before you started
precisely so that it is not yours to move mid-conversation.

When the reader is stuck rather than wrong, narrow rather than repeat. Asking the
same question again in different words is the failure mode of this format.

Do not tell them the answer. If they ask you directly, that is still not a reason
to -- say what you would need them to work out first, and ask about that.
"""

SOCRATIC_FRAMING_PROMPT = """
## Framing this dialogue

The reader has named a topic. Before anything is asked, decide three things and
return them as YAML, and nothing else:

```yaml
goal: |
  What the reader should understand by the end. One sentence, about their
  understanding rather than about the material -- "why the creed's wording
  mattered politically", not "the Nicene creed".
stopping_condition: |
  What the reader will have DONE that shows they got there. It must be something
  you could point at in a transcript: an explanation they gave, a distinction
  they drew, a case they applied it to. Not "understands X" -- that is the goal
  again, and it stops nothing.
opening_prompt: |
  The first question. It should be answerable from what a reader who chose this
  topic already has, because its job is to find out where they are starting.
```

Look at the material first. A goal the project's sources cannot support is one
the dialogue cannot reach, and you will find that out twenty questions in.

Return the YAML block and no other prose.
"""

SOCRATIC_COMPONENT_PROMPT = (
    """
## Asking with something the reader answers

Some questions land better as an item the reader answers than as prose. You can
write an interactive component into your question and it renders as a working
widget.

Two types are available and both are marked on the server, which is the point of
offering them here: a marked answer is *evidence* toward the stopping condition,
where prose is only your reading of it. Use one when you want to know whether the
reader can actually make a distinction, rather than whether they can talk around
it.

Most turns should be a plain question. An item every turn is a quiz, and the
reader will answer it like one. Reach for a component when the distinction you
are testing is one they could talk past.

Never write the answer key into your prose around the item. The reader is shown
the item without it, and a sentence above it that gives it away wastes the one
thing this format buys.

"""
    + component_reference(only=SOCRATIC_COMPONENT_TYPES)
)

SOCRATIC_PROMPT = SOCRATIC_TOOLS_PROMPT + SOCRATIC_METHOD_PROMPT + SOCRATIC_COMPONENT_PROMPT
"""The reply turn. Composed -- see the module docstring for why not appended."""

SOCRATIC_FRAMING_SYSTEM = SOCRATIC_TOOLS_PROMPT + SOCRATIC_FRAMING_PROMPT
"""The framing turn. No component reference: this call returns three strings,
not an utterance to the reader, and offering it widget syntax invites a goal
with an `mcq` in it."""
```

- [ ] **Step 4: Run the prompt tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_socratic_agent.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Prove the composition test red**

Temporarily replace the `SOCRATIC_PROMPT` assignment with:

```python
from research_team.infrastructure.agent.ask_agent import ASK_PROMPT
SOCRATIC_PROMPT = ASK_PROMPT + SOCRATIC_METHOD_PROMPT
```

Re-run. Expected: `test_the_reply_prompt_is_built_from_the_pieces_and_not_from_the_ask_s`
fails, **and** `test_the_socratic_prompt_inherits_nothing_from_the_ask_s_component_reference`
in `tests/application/test_socratic_components.py` fails naming a resolved type.
Note which resolved type it names first. Revert.

This is the repository's convention and it is the one measurement this task
exists to take: the appended version produces a working prompt, so nothing else
in the suite goes red.

- [ ] **Step 6: Confirm Task 1's two deferred tests are now green**

Run: `uv run pytest tests/application/test_socratic_components.py -v`

Expected: PASS, 6 tests — including the two that were red at the end of Task 1.
If either is still red, it is red for a *new* reason and that reason is a real
finding, not a leftover.

- [ ] **Step 7: Wiring**

Run: `uv run pytest tests/test_architecture.py -v`

Expected: PASS. `socratic_agent.py` is in `infrastructure/`, so it may import
LangChain freely — but `socratic_components.py` is in `application/` and must
not. This is the test that says so.

Confirm the prompt is not yet reachable by any model:

Run: `grep -rn "SOCRATIC_PROMPT\|SOCRATIC_FRAMING_SYSTEM" research_team/`

Expected: only `socratic_agent.py` itself. Nothing constructs an executor yet —
Task 3 does, and that is the gap to close, not a silo to worry about.

- [ ] **Step 8: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 9: Commit**

```bash
git add research_team/infrastructure/agent/socratic_agent.py \
  tests/infrastructure/test_socratic_agent.py
git commit -m "Compose the socratic prompt from pieces, never from ASK_PROMPT

ask_agent.py rebinds ASK_PROMPT to carry its component reference, now nine
types at 9,600 characters. Appending to it would inherit six resolved types
silently -- and would work, which is why only a test asserting the ask's own
opening sentence is absent can catch it. What it costs is the surface: a model
given six ways to answer with a drawing, on a page whose method is asking,
writes a slideshow.

Proved red by building it the appending way: the composition test fails and so
does the tuple test from the previous commit, naming a resolved type that
arrived without anyone deciding it should.

Two assembled prompts rather than one, because frame and respond are two jobs.
The framing call turns a topic into a goal, a stopping condition and an opening
question and gets no component reference -- it returns three strings, not an
utterance, and offering it widget syntax invites a goal with an mcq in it. A
single shared prompt would ask the model to re-decide the goal every turn, and
a goal the model can revise mid-dialogue is not a stopping condition anything
can test.

The tools half is shared with the ask agent's claims about the same tools,
deliberately: the tool set is identical and a second drifting description of it
would be a second thing to keep true.

Prompt assertions are structural, not about wording. A test pinning sentences
fails on every improvement and teaches people to delete it.

No executor yet; nothing constructs this."
```

---

### Task 3: The executor, and its composition

**Files:**
- Modify: `research_team/infrastructure/agent/socratic_agent.py` (add the executor)
- Modify: `tests/infrastructure/test_socratic_agent.py` (add the parse tests)
- Modify: `research_team/composition.py` — **all five `_UnbuiltSocraticExecutor`
  lines**: 473 (docstring), 901–918 (delete the class), 1998 (comment), 2007
  (the argument)
- Create: `tests/integration/test_a_dialogue_is_composed_with_a_model.py`

**Interfaces:**
- Consumes: Plan 1's `SocraticExecutor` Protocol, `SocraticFraming`,
  `SocraticPrompt`, `SocraticObservation`, `DialogueMessage`, `Citation`;
  and from `ask_agent.py` — `readable`, `READ_ONLY_FILE_TOOLS`, `CITED_BY_TOOL`;
  from `deep_agent.py` — `to_activity_delta`, `to_activity_message`; from
  `messages.py` — `last_text`; `ReadOnlyProjectBackend`.
- Produces:

```python
class DeepAgentSocraticExecutor:
    def __init__(
        self,
        *,
        model: BaseChatModel,
        open_graph: Callable[[UUID], Awaitable[tuple[Any, tuple[BaseTool, ...]]]],
        project_files: Callable[[UUID], Awaitable[dict[str, Any]]],
        project_sources: Callable[[UUID], Awaitable[dict[str, Any]]],
        system_prompt: str = SOCRATIC_PROMPT,
        framing_prompt: str = SOCRATIC_FRAMING_SYSTEM,
    ) -> None: ...

    async def frame(self, *, project_id: UUID, topic: str) -> SocraticFraming: ...

    async def respond(
        self, *, project_id, history, goal, stopping_condition, reply, on_activity
    ) -> SocraticPrompt: ...

def parse_framing(text: str) -> SocraticFraming: ...
```

  `parse_framing` is module-level and separately testable: it is the one place a
  model's output shape is trusted, and a private method would make the failure
  reachable only through a model call.

- [ ] **Step 1: Write the failing parse tests**

Append to `tests/infrastructure/test_socratic_agent.py`:

```python
import pytest

from research_team.application.socratic import SocraticFraming
from research_team.infrastructure.agent.socratic_agent import parse_framing


def test_a_framing_block_becomes_the_three_strings():
    text = (
        "```yaml\n"
        "goal: |\n"
        "  why the creed's wording mattered politically\n"
        "stopping_condition: |\n"
        "  the reader distinguishes the settlement from the politics around it\n"
        "opening_prompt: |\n"
        "  What do you already believe the creed settled?\n"
        "```\n"
    )

    framing = parse_framing(text)

    assert isinstance(framing, SocraticFraming)
    assert framing.goal == "why the creed's wording mattered politically"
    assert (
        framing.stopping_condition
        == "the reader distinguishes the settlement from the politics around it"
    )
    assert framing.opening_prompt == "What do you already believe the creed settled?"


def test_a_framing_without_a_fence_is_still_read():
    """Models drop the fence roughly as often as they include it, and a framing
    that failed for want of three backticks would fail the whole dialogue at
    its first call. Red against a parser that requires the fence."""
    text = (
        "goal: understand the settlement\n"
        "stopping_condition: the reader explains it unaided\n"
        "opening_prompt: Where would you start?\n"
    )

    framing = parse_framing(text)

    assert framing.goal == "understand the settlement"
    assert framing.opening_prompt == "Where would you start?"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "I would be happy to help you explore this topic!",
        "```yaml\ngoal: only a goal\n```\n",
        "```yaml\ngoal: g\nstopping_condition: s\n```\n",
    ],
)
def test_a_framing_that_is_missing_a_field_is_refused_rather_than_defaulted(text):
    """A dialogue framed with an empty stopping condition is one that can never
    stop, and it would look completely normal until the reader gave up.

    Refused loudly here, at `begin`, where the reader has invested one click --
    rather than defaulted to "" and discovered twenty exchanges later. Red
    against a parser that fills missing keys with empty strings, which is what
    a `.get(key, "")` implementation does.
    """
    with pytest.raises(ValueError, match="framing"):
        parse_framing(text)


def test_a_reply_carries_the_sources_the_agent_actually_opened():
    """`CITED_BY_TOOL` is reused rather than re-derived: `read_source` is still
    the only admitted tool that opens one identified thing, and a second table
    would be a second thing to keep in step with the allowlist."""
    from research_team.infrastructure.agent.ask_agent import CITED_BY_TOOL, READ_SOURCE_TOOL

    assert CITED_BY_TOOL[READ_SOURCE_TOOL] == ("source", "source_id")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/infrastructure/test_socratic_agent.py -x -k "framing or carries_the_sources"`

Expected: FAIL — `ImportError: cannot import name 'parse_framing'`.

- [ ] **Step 3: Write `parse_framing` and the executor**

Append to `socratic_agent.py`. `parse_framing` first:

Its imports, which are not obvious: `_YAML_LOADER` in `components.py` is
private to that module and lives in the **application** layer, so this file
declares its own rather than reaching across for it.

```python
import re
from typing import Any

import yaml

_YAML_LOADER: type = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
"""The fastest *safe* loader this PyYAML has, declared here rather than
imported from `components.py` -- that one is a private name in the application
layer, and infrastructure reaching across for it would be a dependency
`tests/test_architecture.py` does not forbid and nobody wants. `CSafeLoader`
and not `CLoader`: this parses a language model's output, which is exactly the
input that must not be able to construct Python objects."""

_FENCE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)

_FRAMING_FIELDS = ("goal", "stopping_condition", "opening_prompt")


def parse_framing(text: str) -> SocraticFraming:
    """The three strings a framing call must produce, or a refusal.

    **Refused rather than defaulted, and that is the whole of this function.**
    A `.get(key, "")` implementation is one line shorter and produces a
    dialogue framed with an empty stopping condition -- one that can never
    stop, and that looks entirely normal to a reader until they give up. Here
    the failure lands at `begin`, where the reader has spent one click.

    The fence is optional because models include it roughly half the time, and
    a framing that failed for want of three backticks would fail the whole
    dialogue at its first call. `CSafeLoader` for `components.py`'s reason: it
    is the fastest *safe* loader this PyYAML has, and a model's output is
    exactly the input that must not construct Python objects.
    """
    fenced = _FENCE.search(text)
    body = fenced.group(1) if fenced else text
    try:
        loaded = yaml.load(body, Loader=_YAML_LOADER)
    except yaml.YAMLError as error:
        raise ValueError(f"the framing did not parse as YAML: {error}") from error
    if not isinstance(loaded, dict):
        raise ValueError(f"the framing was not a mapping, got {type(loaded).__name__}")
    missing = [
        name
        for name in _FRAMING_FIELDS
        if not isinstance(loaded.get(name), str) or not str(loaded.get(name)).strip()
    ]
    if missing:
        raise ValueError(f"the framing is missing {', '.join(missing)}")
    return SocraticFraming(
        goal=str(loaded["goal"]).strip(),
        stopping_condition=str(loaded["stopping_condition"]).strip(),
        opening_prompt=str(loaded["opening_prompt"]).strip(),
    )
```

Then the executor. Model it on `DeepAgentAskExecutor.run` — read that method and
match its structure, including the `create_deep_agent` call with no checkpointer
and the `astream` loop that translates messages through `to_activity_delta` /
`to_activity_message` and collects citations from `CITED_BY_TOOL`:

```python
class DeepAgentSocraticExecutor:
    """Frames a dialogue and takes one turn in it.

    A sibling of `DeepAgentAskExecutor`, not a subclass: the two share their
    plumbing and differ in their prompts and in what they return, and a shared
    base would put the one interesting difference behind an override.

    Builds a fresh agent per call, as the ask executor does per question and the
    turn executor does per pass -- the tools are bound to a project and a stale
    agent would ask about the wrong one. No checkpointer, for the reason
    `ask_agent.py` records at length: langgraph refuses a checkpointed root
    graph without a `thread_id` and `astream` passes none, so every call would
    raise. Continuity lives in `history`, and the dialogue's *state* lives in
    the aggregate -- which is where a stopping condition has to live to be
    testable at all.

    `frame` reports no activity. It is one short call before the reader has seen
    anything, and a page showing tool chatter under a spinner that has not yet
    said what the dialogue is for reads as noise.
    """

    def __init__(
        self,
        *,
        model: BaseChatModel,
        open_graph: Callable[[UUID], Awaitable[tuple[Any, tuple[BaseTool, ...]]]],
        project_files: Callable[[UUID], Awaitable[dict[str, Any]]],
        project_sources: Callable[[UUID], Awaitable[dict[str, Any]]],
        system_prompt: str = SOCRATIC_PROMPT,
        framing_prompt: str = SOCRATIC_FRAMING_SYSTEM,
    ) -> None:
        self._model = model
        self._open_graph = open_graph
        # Required rather than defaulted, matching `DeepAgentAskExecutor`: a
        # build that forgot to wire it would answer every `grep` over gathered
        # sources with no matches and no error.
        self._project_sources = project_sources
        self._project_files = project_files
        self._system_prompt = system_prompt
        self._framing_prompt = framing_prompt

    async def _agent(self, project_id: UUID, system_prompt: str):
        """One agent, bound to one project. Extracted because `frame` and
        `respond` build the same thing with different instructions."""
        _knowledge, project_tools = await self._open_graph(project_id)
        backend = ReadOnlyProjectBackend(
            await self._project_files(project_id),
            sources=await self._project_sources(project_id),
        )
        return create_deep_agent(
            model=self._model,
            tools=list(readable(project_tools)) or None,
            backend=backend,
            middleware=[FilesystemMiddleware(backend=backend, tools=READ_ONLY_FILE_TOOLS)],
            system_prompt=system_prompt,
        )

    async def frame(self, *, project_id: UUID, topic: str) -> SocraticFraming:
        agent = await self._agent(project_id, self._framing_prompt)
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=f"The reader's topic: {topic}")]}
        )
        return parse_framing(last_text(result["messages"]))

    async def respond(
        self,
        *,
        project_id: UUID,
        history: Sequence[DialogueMessage],
        goal: str,
        stopping_condition: str,
        reply: str,
        on_activity: ActivityReporter,
    ) -> SocraticPrompt:
        """One exchange, reporting activity as it happens.

        Every `on_activity` call is made from inside this coroutine and none is
        deferred to a callback that could outlive it, which is the contract
        `SocraticExecutor` states and `SocraticDialogueService._drain` relies on
        for a final note to reach the reader.

        The goal and the stopping condition are prepended as a system-shaped
        turn rather than baked into `system_prompt`, because they differ per
        dialogue while the prompt is a module constant -- and because a build
        that forgot to pass them would then produce a dialogue with no goal in
        its context and no error, which is the failure this whole feature is
        about.
        """
        agent = await self._agent(project_id, self._system_prompt)
        messages = _framed_history(history, goal, stopping_condition, reply)
        ...
```

For the body of `respond` after `messages`, copy `DeepAgentAskExecutor.run`'s
`astream` loop verbatim in structure — the same `async for` over
`agent.astream(..., stream_mode="messages")`, the same `to_activity_delta` /
`to_activity_message` translation into `on_activity`, and the same citation
collection keyed on `CITED_BY_TOOL`. Read that method and match it; do not invent
a second streaming shape. It ends by returning:

```python
        return SocraticPrompt(
            prompt=last_text(final),
            citations=tuple(citations),
            # `observation` and `concluded` are left at their defaults, and this
            # is a scoped omission with a named owner rather than an oversight.
            #
            # **Until Plan 4 ("concluding a dialogue") lands, nothing anywhere
            # writes `SocraticDialogueConcluded`.** Both fields need the model to
            # return structured judgement alongside its prose, and that parse
            # fails *silently* -- a malformed answer reads as "not concluded"
            # rather than raising -- so it needs its own slice and its own red
            # proofs instead of riding along at the end of this one.
            #
            # Two consequences to know before you touch anything nearby:
            #
            # 1. A dialogue currently ends only when the reader stops replying.
            #    The design's first sentence is that it should stop when the
            #    reader has demonstrated the thing rather than when they stop
            #    typing, so this is the gap between what is built and what was
            #    designed -- not a detail.
            # 2. `SocraticDialogueState.status == "concluded"` and
            #    `SocraticDialogueRow.status`, with the refusal branches in
            #    `socratic_dialogue.decide` behind them, are therefore
            #    **unreachable through any live path** and are exercised only by
            #    unit tests that build the state directly. They are not dead
            #    code. Deleting them is the obvious tidy-up and it would delete
            #    the thing Plan 4 is built on.
            #
            # The graded route (`SocraticDialogueService.record_attempt`) does
            # produce `evidence="attempt"` observations with none of this
            # machinery, which is the half the design argues is worth having
            # first -- so the stopping condition has evidence accumulating
            # against it even while nothing can act on it yet.
        )
```

and `_framed_history`:

```python
def _framed_history(
    history: Sequence[DialogueMessage], goal: str, stopping_condition: str, reply: str
) -> list[BaseMessage]:
    """The conversation, with what it is for in front of it.

    `SystemMessage` rather than a prefix on the first human turn: the framing is
    not something the reader said, and a model shown it as the reader's words
    will sometimes answer it.
    """
    framing = SystemMessage(
        content=(
            f"The goal of this dialogue: {goal}\n"
            f"It stops when: {stopping_condition}\n"
            "Neither is yours to change."
        )
    )
    prior: list[BaseMessage] = [
        HumanMessage(content=message.text)
        if message.role == "user"
        else AIMessage(content=message.text)
        for message in history
    ]
    return [framing, *prior, HumanMessage(content=reply)]
```

- [ ] **Step 4: Run the agent tests**

Run: `uv run pytest tests/infrastructure/test_socratic_agent.py -v`

Expected: PASS, 9 tests.

- [ ] **Step 5: Replace all five seam lines**

Run: `grep -n "_UnbuiltSocraticExecutor" research_team/composition.py`

Expected: 5 hits, at 473, 901, 910, 1998, 2007. Then:

- **901–918**: delete the `_UnbuiltSocraticExecutor` class entirely.
- **473**: rewrite `Application.socratic`'s docstring — it currently says the
  executor is a placeholder and that `begin`/`respond` raise. Replace that
  sentence with what is now true:

```python
    socratic: SocraticDialogueService
    """Guided dialogues: framing a topic, and answering a reply with a question.

    A field beside `ask` and for its reason -- it is composed from this build's
    stores and no caller could assemble it. Its executor closes over the same
    `open_graph` the ask's does, so like `ask` it cannot be constructed anywhere
    a caller could stand."""
```

- **1998 and 2007**: replace the comment and the argument:

```python
    # Built here for `ask_service`'s reason: the executor takes the project
    # tools `open_graph` assembles and keeps the readers, so it cannot be
    # constructed anywhere a caller could reach.
    #
    # A second executor beside the ask's, differently prompted over identical
    # plumbing -- which is the whole of what the design's §4 said this would
    # cost, and it is these four lines.
    #
    # `read_model=dialogues` is the whole of resumption's wiring, and it is one
    # keyword. A build that passed something else here -- or nothing -- would
    # compose, serve, and start every resumed dialogue over.
    socratic_service = SocraticDialogueService(
        executor=DeepAgentSocraticExecutor(
            model=resolved_model,
            open_graph=open_graph,
            project_files=service.project_files,
            project_sources=lambda target_project_id: mounted_sources(
                corpus_readers(target_project_id)
            ),
        ),
        dialogues=DialogueRegistry(now=time.monotonic),
        read_model=dialogues,
        now=time.monotonic,
        transcripts=build_socratic_dialogue_repository(repository.store, repository.publisher),
        clock=lambda: datetime.now(UTC),
    )
```

- [ ] **Step 6: Write the composed integration test**

Create `tests/integration/test_a_dialogue_is_composed_with_a_model.py`:

```python
"""The executor the composition root actually built, over a fake model.

`test_a_dialogue_survives_a_restart.py` replaces `application.socratic._executor`
with a stub, which is right for what it proves and means it would stay green
against a build whose real executor was never constructed -- or was constructed
with the ask's prompt. This file is the one that would not.

The model is `FakeMessagesListChatModel`, so nothing here asserts anything about
a language model's judgement. What it asserts is that a composed `begin` reaches
a model at all, that what comes back is parsed into the three framing strings,
and that those strings land on the stream.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.composition import build_application
from research_team.interfaces.web import create_app

FRAMING = AIMessage(
    content=(
        "```yaml\n"
        "goal: |\n"
        "  why the creed's wording mattered politically\n"
        "stopping_condition: |\n"
        "  the reader separates the settlement from the politics\n"
        "opening_prompt: |\n"
        "  What do you already believe the creed settled?\n"
        "```\n"
    )
)


@pytest.fixture
async def application(tmp_path):
    built = build_application(
        model=FakeMessagesListChatModel(responses=[FRAMING]),
        db_path=str(tmp_path / "composed.db"),
    )
    await built.start()
    yield built
    await built.close()


async def _project(application) -> UUID:
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
        assert created.status_code == 200
        return UUID(created.json()["id"])


async def test_the_composed_executor_frames_a_dialogue_onto_the_stream(application):
    """Red three ways, and the middle one is the reason this file exists:

    1. `_UnbuiltSocraticExecutor` still wired -- `NotImplementedError`.
    2. The real executor wired with `ASK_PROMPT` -- this passes, because a
       fake model ignores its prompt. See the prompt tests for that half; this
       file cannot cover it and says so rather than implying it can.
    3. A `parse_framing` that defaults missing fields -- the goal below comes
       back empty and the assertion names which field.
    """
    project_id = await _project(application)

    dialogue_id = await application.socratic.begin(
        project_id=project_id, topic="the Nicene settlement"
    )
    await application.dialogues.caught_up()

    row = await application.dialogues.get(dialogue_id)
    assert row is not None, "no row: the dialogue projection is not following the log"
    assert row.goal == "why the creed's wording mattered politically"
    assert row.stopping_condition == "the reader separates the settlement from the politics"
    assert row.opening_prompt == "What do you already believe the creed settled?"
    assert row.pending_prompt == row.opening_prompt
    assert row.turn_count == 0


async def test_a_framing_the_model_botched_fails_the_begin_rather_than_the_dialogue(
    tmp_path,
):
    """A model that answered with prose instead of YAML. The dialogue is not
    created at all -- better a failed click than a dialogue with no stopping
    condition, which would look normal until the reader gave up.

    Asserts on the *absence* of a stream, not just on the raise: a `begin` that
    saved the aggregate before framing would leave a goalless dialogue behind
    and still raise.
    """
    from eventsource import collect

    from research_team.domain.socratic_dialogue import SocraticDialogue

    application = build_application(
        model=FakeMessagesListChatModel(
            responses=[AIMessage(content="I'd be happy to explore that with you!")]
        ),
        db_path=str(tmp_path / "botched.db"),
    )
    await application.start()
    try:
        project_id = await _project(application)

        with pytest.raises(ValueError, match="framing"):
            await application.socratic.begin(project_id=project_id, topic="anything")

        store = application.socratic._transcripts.event_store
        written = await collect(store.read_category(SocraticDialogue.aggregate_type))
        assert written == [], "a dialogue was created without a stopping condition"
    finally:
        await application.close()
```

- [ ] **Step 7: Run it**

Run: `uv run pytest tests/integration/test_a_dialogue_is_composed_with_a_model.py -v`

Expected: PASS, 2 tests.

- [ ] **Step 8: Wiring**

Run: `grep -rn "_UnbuiltSocraticExecutor" research_team/ tests/`

Expected: **no hits.** The seam is closed; the class, its two mentions in
comments, its docstring reference and its call site are all gone.

Run: `uv run pytest tests/integration/test_a_dialogue_survives_a_restart.py -v`

Expected: PASS. That file stubs the executor, so it must be unaffected by this
task — if it broke, something changed in the service rather than in the executor.

- [ ] **Step 9: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 10: Commit**

```bash
git add research_team/infrastructure/agent/socratic_agent.py \
  research_team/composition.py \
  tests/infrastructure/test_socratic_agent.py \
  tests/integration/test_a_dialogue_is_composed_with_a_model.py
git commit -m "Put a model behind the dialogue, and close the placeholder seam

A sibling of DeepAgentAskExecutor rather than a subclass. The two share their
plumbing entirely -- same read-only tools, same file backend, same activity
translation -- and differ in their prompts and their return types, and a shared
base would put the one interesting difference behind an override.

parse_framing refuses rather than defaults, and that is the whole of it. A
.get(key, '') implementation is a line shorter and produces a dialogue framed
with an empty stopping condition: one that can never stop, and that looks
entirely normal to a reader until they give up. Refusing puts the failure at
begin, where the reader has spent one click. The composed test asserts no
stream was written, not merely that it raised -- a begin that saved before
framing would leave a goalless dialogue behind and raise anyway.

The fence around the YAML is optional because models include it about half the
time, and a framing that failed for want of three backticks would fail every
dialogue at its first call.

observation and concluded stay at their defaults. Both need the model to report
structured judgement alongside prose -- a second parse with its own failure
modes -- and the graded route in the next commit produces attempt-backed
observations without any of it, which is the half worth having first.

_UnbuiltSocraticExecutor is gone: the class, both comments, the Application
docstring and the call site. grep finds nothing.

The composed test uses a fake model, so it says nothing about judgement. It
also cannot catch the executor being wired with ASK_PROMPT -- a fake model
ignores its prompt -- and its docstring says so rather than implying otherwise.
The prompt tests are that half."
```

---

### Task 4: The routes and the stream

**Files:**
- Modify: `research_team/interfaces/web/app.py` — `SocraticStart` and
  `SocraticReply` body models beside `AskRequest` (~line 663); `socratic:
  SocraticDialogueService | None = None` on `create_app` beside `ask` (~line 729);
  `_socratic_frame` and the two POST routes beside the ask routes (~line 2975)
- Modify: `web.py` — `socratic=application.socratic` in the `create_app` call
- Create: `tests/integration/test_socratic_stream.py`

**Interfaces:**
- Consumes: `application.socratic`; `SocraticDialogueOpened`, `SocraticPrompt`,
  `UnknownDialogue`, `DialogueInFlight`; `ActivityDelta`, `ActivityMessage`;
  `dialogue_document` (Task 1).
- Produces:

```python
class SocraticStart(BaseModel):
    topic: str

class SocraticReply(BaseModel):
    reply: str

# POST /api/projects/{project_id}/dialogues        -> {"dialogueId": "..."}
# POST /api/projects/{project_id}/dialogues/{dialogue_id}/reply -> text/event-stream
```

  SSE frame types, which Plan 3's DTOs are written against:

| `type` | fields |
| --- | --- |
| `dialogue` | `dialogue_id`, `goal`, `stopping_condition`, `pending_prompt` |
| `delta` | `message_id`, `text` |
| `message` | `message_id`, `kind`, `payload`, `is_error` |
| `prompt` | `text`, `blocks`, `position`, `citations`, `concluded` |
| `error` | `detail` |

  `prompt` rather than `answer`, deliberately: the last frame of a dialogue turn
  is a question, and Plan 3 must not reuse the ask's `answer` handler for it.

- [ ] **Step 1: Write the failing route tests**

Create `tests/integration/test_socratic_stream.py`:

```python
"""The two POST routes, over a composed application with a stubbed executor.

The executor is stubbed and the model is fake: what is under test is the route
and the frames, not judgement. Every assertion about persistence reads a row --
a 200 with a well-formed stream is compatible with nothing having been written,
because an event no projection handles counts as applied.
"""

import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import (
    SocraticFraming,
    SocraticObservation,
    SocraticPrompt,
)
from research_team.composition import build_application
from research_team.interfaces.web import create_app

MCQ = (
    "Try this one:\n\n"
    "```component:mcq\n"
    "id: council-1\n"
    "prompt: Which council?\n"
    "options:\n"
    '  - text: "Nicaea"\n'
    "    correct: true\n"
    '  - text: "Chalcedon"\n'
    "    correct: false\n"
    "```\n"
)


class StubExecutor:
    """Frames once, then asks whatever it was handed, in order."""

    def __init__(self, prompts=None) -> None:
        # `is not None`, never `or`: an empty list is a legitimate argument and
        # `or` would silently substitute the default. Plan 1 was bitten by this
        # twice, once fatally -- see `DialogueRegistry.__bool__`.
        self._prompts = list(prompts) if prompts is not None else [SocraticPrompt(prompt="Why?")]
        self.calls: list[dict] = []

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition="the reader explains it unaided",
            opening_prompt="Where would you start?",
        )

    async def respond(self, *, project_id, history, goal, stopping_condition, reply, on_activity):
        self.calls.append({"reply": reply, "goal": goal, "history": len(history)})
        return self._prompts.pop(0)


@pytest.fixture
async def client(tmp_path):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]),
        db_path=str(tmp_path / "stream.db"),
    )
    await application.start()
    stub = StubExecutor([SocraticPrompt(prompt="Why do you say that?", position=0)])
    application.socratic._executor = stub
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        socratic=application.socratic,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, application, stub
    await application.close()


async def _project(http) -> UUID:
    created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
    assert created.status_code == 200
    return UUID(created.json()["id"])


def _frames(body: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


async def test_starting_a_dialogue_returns_its_id_and_writes_its_framing(client):
    """The id is the server's and is the only way back to this dialogue, so it
    has to be in the response body -- there is no registry key a browser could
    reconstruct it from.

    The row assertion is the one that matters: a 200 carrying an id is
    compatible with nothing having been written.
    """
    http, application, _stub = client
    project_id = await _project(http)

    response = await http.post(
        f"/api/projects/{project_id}/dialogues", json={"topic": "the Nicene settlement"}
    )

    assert response.status_code == 200, response.text
    dialogue_id = UUID(response.json()["dialogueId"])
    await application.dialogues.caught_up()

    row = await application.dialogues.get(dialogue_id)
    assert row is not None, "no row: the projection is not following the log"
    assert row.goal == "understand the Nicene settlement"
    assert row.opening_prompt == "Where would you start?"


async def test_a_reply_streams_the_framing_first_and_the_question_last(client):
    """Frame order is the contract Plan 3 renders against. The framing frame
    comes first so a page can show what the dialogue is for -- and which
    question is outstanding -- before the model has produced anything.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(
        f"/api/projects/{project_id}/dialogues", json={"topic": "the Nicene settlement"}
    )
    dialogue_id = started.json()["dialogueId"]

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
        json={"reply": "It settled Arianism."},
    )

    assert response.status_code == 200, response.text
    frames = _frames(response.text)
    assert frames[0]["type"] == "dialogue"
    assert frames[0]["dialogue_id"] == dialogue_id
    assert frames[0]["goal"] == "understand the Nicene settlement"
    assert frames[0]["stopping_condition"] == "the reader explains it unaided"
    # The question the reader was answering, not the one about to be asked.
    assert frames[0]["pending_prompt"] == "Where would you start?"
    assert frames[-1]["type"] == "prompt"
    assert frames[-1]["text"] == "Why do you say that?"
    assert frames[-1]["position"] == 0
    assert frames[-1]["concluded"] is False

    await application.dialogues.caught_up()
    turns = await application.dialogues.turns_for(UUID(dialogue_id))
    assert [(t.reply, t.prompt) for t in turns] == [
        ("It settled Arianism.", "Why do you say that?")
    ]


async def test_the_last_frame_is_typed_prompt_and_not_answer(client):
    """Plan 3 must not reuse the ask's `answer` handler for this frame: the
    last thing a dialogue turn produces is a question, and a page that rendered
    it as an answer would draw the dialogue's question in the reader's own
    column. Red against a `_socratic_frame` copy-pasted from `_ask_frame`.
    """
    http, _application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "hello"}
    )

    assert {frame["type"] for frame in _frames(response.text)} == {"dialogue", "prompt"}


async def test_a_component_in_a_question_arrives_parsed_and_withheld(tmp_path):
    """Parsed on the server for `components.py`'s four reasons, of which the
    second binds: withholding is only real if the projection happens before the
    bytes leave. Red against a frame that ships `text` alone and lets the
    browser parse -- the key travels either way, and the blocks are what the
    page renders.
    """
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "cmp.db")
    )
    await application.start()
    try:
        application.socratic._executor = StubExecutor([SocraticPrompt(prompt=MCQ)])
        api = create_app(
            application.service,
            application.feed,
            application.turns,
            socratic=application.socratic,
        )
        transport = ASGITransport(app=api)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            project_id = await _project(http)
            started = await http.post(
                f"/api/projects/{project_id}/dialogues", json={"topic": "t"}
            )
            dialogue_id = started.json()["dialogueId"]
            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
                json={"reply": "Nicaea, I think"},
            )

        last = _frames(response.text)[-1]
        kinds = [block["kind"] for block in last["blocks"]]
        assert kinds == ["markdown", "component"]
        component = last["blocks"][1]
        assert component["type"] == "mcq"
        assert component["withheld"], "the answer key reached the browser"
        assert "correct" not in json.dumps(component["data"])
    finally:
        await application.close()


async def test_a_dialogue_that_does_not_exist_is_a_404_not_a_new_one(client):
    """`UnknownDialogue` covers a guessed id, a stale one and a concluded one,
    and all three are 404 -- telling a caller that an id they cannot use does
    exist is the distinction not worth drawing.

    404 and not a stream carrying an error frame: this is raised by `_resume`
    before any note is yielded, so it can still be a status code, which is the
    same split `ask_project` makes for `AskInFlight`.
    """
    http, _application, _stub = client
    project_id = await _project(http)

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{uuid4()}/reply", json={"reply": "hello?"}
    )

    assert response.status_code == 404, response.text


async def test_a_second_reply_while_one_is_running_is_a_409(client):
    """`DialogueInFlight`, raised before streaming begins, so it can be a
    status code the page can act on rather than an error frame it has to
    special-case."""
    import asyncio

    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    release = asyncio.Event()

    class SlowExecutor(StubExecutor):
        async def respond(self, **kwargs):
            await release.wait()
            return SocraticPrompt(prompt="Why?")

    application.socratic._executor = SlowExecutor()
    first = asyncio.create_task(
        http.post(
            f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
            json={"reply": "one"},
        )
    )
    await asyncio.sleep(0.05)
    second = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "two"}
    )
    release.set()
    await first

    assert second.status_code == 409, second.text


async def test_an_unconfigured_build_says_so_rather_than_answering(tmp_path):
    """503 when the service is unwired, matching `ask_project`. A build with no
    `socratic=` is not a build with no dialogues -- it is one that cannot hold
    them, and the two must not look alike."""
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "bare.db")
    )
    await application.start()
    try:
        api = create_app(application.service, application.feed, application.turns)
        transport = ASGITransport(app=api)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            project_id = await _project(http)
            response = await http.post(
                f"/api/projects/{project_id}/dialogues", json={"topic": "t"}
            )
            assert response.status_code == 503, response.text
    finally:
        await application.close()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/integration/test_socratic_stream.py -x`

Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'socratic'`.

- [ ] **Step 3: Add the body models and the parameter**

Beside `AskRequest` in `app.py`:

```python
class SocraticStart(BaseModel):
    """A topic to build a dialogue around.

    No id: unlike an ask's `chat_id`, the dialogue's id is minted by the server
    and returned, because it is an aggregate id, a row key and a URL segment --
    the identical hazard as letting a browser or a model pick one.
    """

    topic: str


class SocraticReply(BaseModel):
    """What the reader said in answer to the outstanding question.

    Named `reply` and not `question`, matching the domain: on this surface the
    system asks and the reader answers, which is the inverse of the ask.
    """

    reply: str
```

Add to `create_app`'s signature, beside `ask`:

```python
    socratic: SocraticDialogueService | None = None,
```

- [ ] **Step 4: Add the frame function and the two routes**

Beside the ask routes:

```python
    def _socratic_frame(note: object) -> str:
        """One SSE `data:` line per note.

        Deliberately its own function rather than a branch inside `_ask_frame`:
        the last frame of a dialogue turn is typed `prompt` and not `answer`,
        because it is a question. A page that reused the ask's handler would
        draw the dialogue's question in the reader's own column -- and it would
        render, which is why this is a separate function with its own test.
        """
        if isinstance(note, SocraticDialogueOpened):
            body: dict[str, Any] = {
                "type": "dialogue",
                "dialogue_id": str(note.dialogue_id),
                "goal": note.goal,
                "stopping_condition": note.stopping_condition,
                # The question being answered, not the one about to be asked.
                # On a resumed dialogue this is not the opening one, which is
                # why the field is not called `opening_prompt`.
                "pending_prompt": note.pending_prompt,
            }
        elif isinstance(note, ActivityDelta):
            body = {"type": "delta", "message_id": note.message_id, "text": note.text}
        elif isinstance(note, ActivityMessage):
            body = {
                "type": "message",
                "message_id": note.message_id,
                "kind": note.kind,
                "payload": note.payload,
                "is_error": note.is_error,
            }
        elif isinstance(note, SocraticPrompt):
            body = {
                "type": "prompt",
                "text": note.prompt,
                # Parsed here rather than in the browser, for the reasons
                # `components.py` opens with -- the second binds hardest:
                # withholding is only real if the projection happens before the
                # bytes leave, and this surface is the one where being told the
                # answer defeats the method rather than merely leaking.
                "blocks": dialogue_document(note.prompt)["blocks"],
                "position": note.position,
                "citations": [
                    {"kind": kind, "id": cited} for kind, cited in note.citations
                ],
                "concluded": note.concluded,
            }
        else:  # ActivityRemark and anything added later
            body = {"type": "message", "message_id": "", "kind": "assistant", "payload": {}}
        return f"data: {json.dumps(body)}\n\n"

    @app.post("/api/projects/{project_id}/dialogues")
    async def start_dialogue(project_id: UUID, body: SocraticStart):
        """Frame a dialogue and return its id.

        Not a stream, unlike the reply route: framing produces three strings and
        no activity worth watching, and a page that opened an EventSource for it
        would show a spinner over an empty transcript. The reader's first sight
        of the dialogue is its goal, and that arrives here.

        A framing the model botched raises `ValueError` out of `parse_framing`
        and becomes a 502: the request was fine and the upstream was not, which
        is a different thing to tell a reader than a 400.
        """
        if socratic is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        if service is not None:
            await _require_project(project_id)
        try:
            dialogue_id = await socratic.begin(project_id=project_id, topic=body.topic)
        except ValueError as bad_framing:
            raise HTTPException(
                status_code=502, detail=f"the dialogue could not be framed: {bad_framing}"
            ) from bad_framing
        return {"dialogueId": str(dialogue_id)}

    @app.post("/api/projects/{project_id}/dialogues/{dialogue_id}/reply")
    async def reply_to_dialogue(project_id: UUID, dialogue_id: UUID, body: SocraticReply):
        """Answer the outstanding question, and stream the next one.

        The same two-stage shape as `ask_project`, and for the same reason: the
        first note is pulled before the response begins so that the failures
        which can still be a status code -- 404 for an unknown dialogue, 409 for
        one already running -- are status codes rather than error frames the
        page has to special-case.
        """
        if socratic is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        if service is not None:
            await _require_project(project_id)

        notes = socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply=body.reply
        )
        failed: Exception | None = None
        try:
            first = await anext(notes)
        except UnknownDialogue as missing:
            # Covers a guessed id, a stale one, and a concluded one. All 404:
            # telling a caller that an id they cannot use does exist is the
            # distinction not worth drawing.
            raise HTTPException(status_code=404, detail=str(missing)) from missing
        except DialogueInFlight as busy:
            raise HTTPException(status_code=409, detail=str(busy)) from busy
        except StopAsyncIteration:
            first = None
        except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
            first, failed = None, failure

        async def stream():
            try:
                if failed is not None:
                    raise failed
                if first is not None:
                    yield _socratic_frame(first)
                async for note in notes:
                    yield _socratic_frame(note)
            except Exception as failure:  # noqa: BLE001
                yield f"data: {json.dumps({'type': 'error', 'detail': str(failure)})}\n\n"
            finally:
                # The only path that cancels the executor task when a reader
                # walks away. See `ask_project`'s `finally` for when this
                # actually runs -- it is generator finalisation, not disconnect.
                await notes.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
```

- [ ] **Step 5: Run the route tests to verify they pass**

Run: `uv run pytest tests/integration/test_socratic_stream.py -v`

Expected: PASS, 7 tests.

- [ ] **Step 6: Wire the entrypoint — and watch a test demand it**

Run: `uv run pytest tests/interfaces/test_web_entrypoint.py -v`

Expected: **FAIL**, naming `socratic` —
`web.py does not pass ['socratic'] to create_app`. That test reads
`create_app`'s signature at test time, so adding the parameter is what makes it
start demanding the call site. **This is the guard, and watching it go red is the
point of this step.**

Then add to `web.py`'s `create_app(...)` call, beside `ask=application.ask`:

```python
            # The write side of dialogues. `ask` above has the same shape and
            # the same history: routes added to `create_app` and not to this
            # call have shipped 503ing three times while every test built its
            # own app and passed. `test_web_entrypoint.py` exists for that and
            # is what went red when this parameter was added.
            socratic=application.socratic,
```

Re-run: `uv run pytest tests/interfaces/test_web_entrypoint.py -v` → PASS.

- [ ] **Step 7: Wiring — the whole chain**

| Link | Where | Confirm |
| --- | --- | --- |
| prompt reaches the model | `socratic_agent.SOCRATIC_PROMPT` | Task 2's tests |
| executor constructed | `composition.py` | `DeepAgentSocraticExecutor(...)`, no `_Unbuilt` |
| service holds it | `Application.socratic` | Task 3's composed test |
| route holds the service | `create_app(socratic=...)` | this task |
| **entrypoint passes it** | `web.py` | `test_web_entrypoint.py` |
| frames typed for the reader | `_socratic_frame` | `prompt`, not `answer` |
| components projected | `dialogue_document` | `withheld` non-empty |

Run: `uv run pytest tests/integration/ tests/interfaces/ -v`

Expected: PASS. The ask routes share `create_app`'s signature and this task
changed it.

**Note for whoever runs Plan 1's Task 5:** it adds `dialogues=` to the same
signature and the same `web.py` call. Two parameters, both required by
`test_web_entrypoint.py` once present. Do not delete this one while adding that.

- [ ] **Step 8: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 9: Commit**

```bash
git add research_team/interfaces/web/app.py web.py \
  tests/integration/test_socratic_stream.py
git commit -m "Hold a dialogue over HTTP: start it, answer it, stream the next question

Two routes with deliberately different shapes. Starting is not a stream:
framing produces three strings and no activity worth watching, and a page that
opened an EventSource for it would show a spinner over an empty transcript. The
reader's first sight of a dialogue is its goal, and that arrives in the POST
body.

_socratic_frame is its own function and not a branch in _ask_frame. The last
frame of a dialogue turn is typed prompt, not answer, because it is a question
-- and a page that reused the ask's handler would draw the dialogue's question
in the reader's own column, and it would render. That is why the frame type has
a test of its own rather than being left to Plan 3 to notice.

Components are parsed server-side before the bytes leave, which is where
withholding is real rather than ceremonial. It matters more here than on the
ask: being told the answer defeats a surface whose whole method is asking,
where on an ask it merely leaks.

404 covers a guessed id, a stale one and a concluded one, all raised by _resume
before any note is yielded so they can still be status codes. 409 for a
dialogue already running, same split as AskInFlight. 502 and not 400 for a
framing the model botched: the request was fine and the upstream was not.

web.py passes socratic=. test_web_entrypoint.py went red the moment the
parameter was added -- it reads create_app's signature at test time -- which is
the guard that exists because this exact bug shipped three times."
```

---

### Task 5: Attempts, recorded against the dialogue

**Files:**
- Modify: `research_team/application/socratic.py` — `record_attempt` on the
  service, and `progress` on its constructor
- Modify: `research_team/composition.py` — pass `progress=` to
  `SocraticDialogueService`
- Modify: `research_team/interfaces/web/app.py` — `SocraticAttempt` body model
  and the attempts route
- Create: `tests/integration/test_socratic_attempts.py`

**Interfaces:**
- Consumes: `grade`, `GradingError`, `Verdict` (`application.grading`);
  `RecordAttempt`, `LearnerProgress`, `LearnerProgressState` and
  `initial_state as learner_initial_state` (`domain.learner`);
  `build_learner_progress_repository` (`infrastructure.persistence.event_store`);
  `parse_document`; `ObserveSocraticProgress` (Plan 1);
  **`item_view` from `research_team.interfaces.web.presenters`** — it is already
  imported in `app.py` for the lesson attempts route; confirm with
  `grep -n "item_view" research_team/interfaces/web/app.py` before adding a
  second import.
- Produces:

```python
# on SocraticDialogueService.__init__, a new keyword:
#   progress: AggregateRepository[LearnerProgress] | None = None

async def record_attempt(
    self,
    *,
    project_id: UUID,
    dialogue_id: UUID,
    position: int,
    component_id: str,
    component_type: str,
    digest: str,
    response: Any,
    correct: bool,
    score: float,
    observation: str,
) -> LearnerProgressState: ...

class SocraticAttempt(BaseModel):
    position: int
    component_id: str
    response: Any = None

# POST /api/projects/{project_id}/dialogues/{dialogue_id}/attempts
#   -> verdict.as_json() | {"progress": item}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_socratic_attempts.py`:

```python
"""Marking an answer inside a dialogue, and what it leaves behind.

Two writes per attempt and both are asserted on stored facts, never on the 200:
a `LearnerProgress` attempt keyed on the DIALOGUE id (design §3), and a
`SocraticProgressObserved` with `evidence="attempt"` on the dialogue's own
stream. Without the second, grading in a dialogue is grading in an ask -- a
verdict shown and forgotten -- and the design's whole argument for answering
B33 here is that a marked answer is evidence toward the stopping condition.
"""

import json
from uuid import UUID, uuid4

import pytest
from eventsource import StreamId, collect
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticProgressObserved,
)
from research_team.interfaces.web import create_app

MCQ = (
    "```component:mcq\n"
    "id: council-1\n"
    "prompt: Which council?\n"
    "options:\n"
    '  - text: "Nicaea"\n'
    "    correct: true\n"
    '  - text: "Chalcedon"\n'
    "    correct: false\n"
    "```\n"
)


class StubExecutor:
    def __init__(self, prompts=None, opening="Where would you start?") -> None:
        self._prompts = list(prompts) if prompts is not None else [SocraticPrompt(prompt=MCQ)]
        self._opening = opening

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition="the reader explains it unaided",
            opening_prompt=self._opening,
        )

    async def respond(self, **_kwargs):
        return self._prompts.pop(0)


async def _app(tmp_path, executor):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "att.db")
    )
    await application.start()
    application.socratic._executor = executor
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        socratic=application.socratic,
    )
    return application, AsyncClient(transport=ASGITransport(app=api), base_url="http://test")


async def _project(http) -> UUID:
    created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
    assert created.status_code == 200
    return UUID(created.json()["id"])


async def _dialogue_with_an_mcq(http, project_id) -> str:
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]
    await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
        json={"reply": "not sure"},
    )
    return dialogue_id


async def test_a_correct_answer_is_marked_and_recorded_against_the_dialogue(tmp_path):
    """Both writes, both asserted on stored facts.

    Red against a route that grades and returns without recording -- which is
    exactly what the ask's attempts route does, deliberately, and is the shape
    someone reusing it would produce here.
    """
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id = await _dialogue_with_an_mcq(http, project_id)

            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 0},
            )

        assert response.status_code == 200, response.text
        assert response.json()["correct"] is True

        # Write one: progress, keyed on the dialogue id rather than a session.
        progress = await application.socratic.progress_for(UUID(dialogue_id))
        item = progress.item("turn/0", "council-1")
        assert item is not None, "no progress row: the attempt was graded and forgotten"
        assert item.correct is True

        # Write two: the dialogue's own stream, so the stopping condition has
        # something to be met by.
        stream = StreamId(UUID(dialogue_id), SocraticDialogue.aggregate_type)
        events = [
            envelope.event
            for envelope in await collect(
                application.socratic._transcripts.event_store.read_stream(stream)
            )
        ]
        observed = [e for e in events if isinstance(e, SocraticProgressObserved)]
        assert len(observed) == 1
        assert observed[0].evidence == "attempt"
        assert "council-1" in observed[0].detail
    finally:
        await application.close()


async def test_a_wrong_answer_is_a_200_and_is_still_evidence(tmp_path):
    """A wrong answer is a result, not an error -- and it is still something
    the reader demonstrated, so it is still observed. A dialogue that only
    recorded correct answers would have a stopping condition fed by a biased
    sample of the reader's attempts.
    """
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id = await _dialogue_with_an_mcq(http, project_id)
            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 1},
            )

        assert response.status_code == 200, response.text
        assert response.json()["correct"] is False

        stream = StreamId(UUID(dialogue_id), SocraticDialogue.aggregate_type)
        events = [
            envelope.event
            for envelope in await collect(
                application.socratic._transcripts.event_store.read_stream(stream)
            )
        ]
        observed = [e for e in events if isinstance(e, SocraticProgressObserved)]
        assert len(observed) == 1
        assert observed[0].evidence == "attempt"
    finally:
        await application.close()


async def test_the_component_is_addressed_by_position_and_a_wrong_one_is_a_404(tmp_path):
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id = await _dialogue_with_an_mcq(http, project_id)

            no_such_turn = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 7, "component_id": "council-1", "response": 0},
            )
            no_such_component = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "nope", "response": 0},
            )

        assert no_such_turn.status_code == 404, no_such_turn.text
        assert no_such_component.status_code == 404, no_such_component.text
    finally:
        await application.close()


async def test_a_response_the_item_cannot_interpret_is_a_400(tmp_path):
    """A malformed request, unlike a wrong answer. `GradingError` is the split
    and it is the same one the ask and lesson routes make."""
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id = await _dialogue_with_an_mcq(http, project_id)
            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": "Nicaea"},
            )

        assert response.status_code == 400, response.text
    finally:
        await application.close()


@pytest.mark.parametrize("opening", ["Where would you start?", ""])
async def test_the_grading_key_survives_a_dialogue_with_no_opening_question(
    tmp_path, opening
):
    """The position-formula parity case, made visible.

    `SocraticPrompt.position` is `len(messages) // 2`. It was `(len - 1) // 2`
    for a commit, and the two agree on every ODD history -- which is what a
    dialogue with an opening question always has. They differ only when
    `_resume` finds an empty `opening_prompt`, which `SocraticDialogueStarted`
    permits and older streams therefore produce.

    **This route is where that becomes visible to a reader**, because `position`
    is half the grading key: with the wrong formula, exchange 1 of a dialogue
    with no opening question is numbered 0, collides with exchange 0, and the
    reader's answer is marked against a component they were never shown -- or
    404s.

    Parametrised over both parities for that reason. The first case passes
    under either formula and is here to prove the second is not passing by
    accident.
    """
    application, client = await _app(tmp_path, StubExecutor(opening=opening))
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id = await _dialogue_with_an_mcq(http, project_id)

            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 0},
            )

        assert response.status_code == 200, response.text
        progress = await application.socratic.progress_for(UUID(dialogue_id))
        assert progress.item("turn/0", "council-1") is not None
    finally:
        await application.close()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/integration/test_socratic_attempts.py -x`

Expected: FAIL — 404 from FastAPI, because the attempts route does not exist.

- [ ] **Step 3: Add `record_attempt` and `progress_for` to the service**

In `research_team/application/socratic.py`, add a `progress` keyword to
`__init__` — **optional, and defaulted with `is not None`, never `or`**:

```python
        progress: AggregateRepository[LearnerProgress] | None = None,
```

```python
        # Optional, unlike `read_model`: a build without it grades and does not
        # remember, which is a degradation a reader can live with, where a build
        # without a read model resumes wrongly and cannot. Checked with
        # `is not None` at every use -- an `or` here is the shape that has
        # already cost this feature two debugging sessions.
        self._progress = progress
```

Then:

```python
    async def progress_for(self, dialogue_id: UUID) -> LearnerProgressState:
        """What this reader has answered in this dialogue.

        Keyed on the dialogue id, which is the design's §3 in one line: a
        dialogue has a durable id, survives eviction, and means exactly "one
        reader working toward one goal" -- the thing `LearnerProgress` needs and
        an ask does not have. This answers B33 **for this surface only**; an ask
        still records nothing, and generalising this is a separate decision with
        a separate argument.
        """
        if self._progress is None:
            return learner_initial_state()
        aggregate = await self._progress.load_or_create(dialogue_id)
        return aggregate.state

    async def record_attempt(
        self,
        *,
        project_id: UUID,
        dialogue_id: UUID,
        position: int,
        component_id: str,
        component_type: str,
        digest: str,
        response: Any = None,
        correct: bool = False,
        score: float = 0.0,
        observation: str = "",
    ) -> LearnerProgressState:
        """Record one marked answer, twice.

        **Two writes, and the second is the reason this method exists rather
        than a call to `SessionService.record_attempt`.** The first is the
        ordinary progress attempt, keyed on the dialogue. The second is a
        `SocraticProgressObserved` with `evidence="attempt"` on the dialogue's
        own stream, which is what lets a stopping condition be met by something
        the reader *did* rather than by the model's opinion of what they said.
        Drop it and grading here is grading in an ask: a verdict shown and
        forgotten.

        `path` is `turn/{position}` because `LearnerProgress.decide` refuses an
        empty path and a dialogue has no file. The progress id is already the
        dialogue, so what `path` disambiguates is which exchange -- see
        `SocraticPrompt.position` for why that number is `len(messages) // 2`
        and what the other formula costs here specifically.

        The observation is written even for a wrong answer. A stopping condition
        fed only by correct attempts is fed by a biased sample of what the
        reader actually did.
        """
        # The dialogue's own stream FIRST, the progress attempt second, and the
        # order is deliberate rather than incidental.
        #
        # These are two aggregates and there is no transaction across them, so
        # one of the two can land alone. Which one is the survivable half is the
        # whole question. Observation-then-attempt leaves a dialogue that knows
        # the reader answered something and a progress record that never got
        # written -- the reader loses a tick and the stopping condition still
        # has its evidence. Attempt-then-observation leaves the opposite: a
        # progress row nothing points at, and a stopping condition missing the
        # one thing that was supposed to feed it, with the reader's screen
        # showing the answer marked. The second failure is invisible and
        # permanent; the first is visible and costs a tick.
        #
        # `observation` defaults with `or` here and that is safe, unlike the
        # collaborator defaults elsewhere in this module: the fallback is a
        # *string*, an empty one carries no information, and there is no object
        # being silently substituted. See `DialogueRegistry.__bool__` for the
        # case where this idiom was genuinely wrong.
        observed = ObserveSocraticProgress(
            dialogue_id=dialogue_id,
            observation=observation
            or f"answered {component_id} {'correctly' if correct else 'incorrectly'}",
            evidence="attempt",
            detail=f"{component_type} {component_id} at turn {position}: "
            f"{'correct' if correct else 'incorrect'}",
        )
        aggregate = await self._transcripts.load(dialogue_id)
        aggregate.execute(observed)
        await self._transcripts.save(aggregate)

        if self._progress is None:
            return learner_initial_state()
        progress = await self._progress.load_or_create(dialogue_id)
        progress.execute(
            RecordAttempt(
                progress_id=dialogue_id,
                path=f"turn/{position}",
                component_id=component_id,
                component_type=component_type,
                digest=digest,
                response=response,
                correct=correct,
                score=score,
            )
        )
        await self._progress.save(progress)
        return progress.state
```

The ordering comment above `observed` is not optional prose — it is the reason
these two writes are in the order they are, and the "simplification" that swaps
them produces the one failure mode that is both invisible and permanent. Keep it
in the code, not only here.

- [ ] **Step 4: Pass `progress` from composition**

In `composition.py`, add to the `SocraticDialogueService(...)` construction:

```python
        # The same builder `SessionService` uses, over the same log. Keyed on
        # the dialogue id here rather than a session id -- see
        # `SocraticDialogueService.progress_for` and the design's §3 for why
        # this surface can answer the identity question the ask path skipped.
        progress=build_learner_progress_repository(
            repository.store, repository.publisher, snapshot_store=repository.snapshot_store
        ),
```

- [ ] **Step 5: Add the route**

Beside `SocraticReply` in `app.py`:

```python
class SocraticAttempt(BaseModel):
    """One reader's answer to a component the dialogue asked.

    Addressed by `(position, component_id)`, matching `AskAttempt`: a dialogue
    turn has no file path, and the turn is what the server re-parses to recover
    the key. No `at` -- a `SocraticTurnRecorded` is never rewritten, so there is
    no second version to grade against.
    """

    position: int
    component_id: str
    response: Any = None
```

and the route, beside the reply route:

```python
    @app.post("/api/projects/{project_id}/dialogues/{dialogue_id}/attempts")
    async def post_dialogue_attempt(
        project_id: UUID, dialogue_id: UUID, body: SocraticAttempt
    ):
        """Mark one attempt at a component the dialogue asked, and remember it.

        **Unlike `post_ask_attempt`, this records.** An ask has no identity to
        record against; a dialogue is one -- a durable id meaning exactly "one
        reader working toward one goal" -- which is the design's §3 and the
        reason this surface can answer a question the ask path was allowed to
        skip. The visible difference is that a refresh does not blank the
        widgets here.

        The key is recovered by re-parsing the stored turn's `prompt`, which is
        the dialogue's utterance -- not `reply`, which is the reader's. Parsed
        raw and never through `project()`: that call is what strips the key for
        a browser, and this is the one caller that needs it.
        """
        if socratic is None or dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        turn = next(
            (t for t in await dialogues.turns_for(dialogue_id) if t.position == body.position),
            None,
        )
        if turn is None:
            raise HTTPException(
                status_code=404,
                detail=f"dialogue {dialogue_id} has no turn {body.position}",
            )
        component = parse_document(turn.prompt, path="").component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"turn {body.position} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        progress = await socratic.record_attempt(
            project_id=project_id,
            dialogue_id=dialogue_id,
            position=body.position,
            component_id=body.component_id,
            component_type=component.type,
            digest=hashlib.sha256(component.raw.encode("utf-8")).hexdigest(),
            response=body.response,
            correct=verdict.correct,
            score=verdict.score,
        )
        return verdict.as_json() | {
            "progress": item_view(progress, f"turn/{body.position}", body.component_id)
        }
```

**This route needs `dialogues` as well as `socratic`.** That parameter is Plan
1's Task 5. If Task 5 has not landed when you reach this step, add
`dialogues: SocraticDialogueRunner | None = None` to `create_app` here and to
`web.py` — and say in the commit that Plan 1's Task 5 will find it already
present and should not add a second one.

- [ ] **Step 6: Run the attempt tests**

Run: `uv run pytest tests/integration/test_socratic_attempts.py -v`

Expected: PASS, 6 tests (the parity test is parametrised over two).

- [ ] **Step 7: Prove the parity test red**

Change `SocraticPrompt`'s position assignment in `socratic.py:respond` from
`len(dialogue.messages) // 2` to `(len(dialogue.messages) - 1) // 2` and re-run.

Expected: `test_the_grading_key_survives_a_dialogue_with_no_opening_question[]`
— the empty-opening case — fails with a 404, while the
`[Where would you start?]` case still passes. Revert.

That asymmetry is the whole finding: the odd-length case cannot tell the
formulas apart, which is how the wrong one survived a review.

- [ ] **Step 8: Wiring**

Run: `grep -n "progress=" research_team/composition.py`

Expected: two hits — `SessionService`'s and `SocraticDialogueService`'s, both
from `build_learner_progress_repository` over the same store. A dialogue's
progress and a session's share a log and are kept apart by aggregate id, which
is what `LearnerProgress` already does for sessions.

Run: `uv run pytest tests/interfaces/test_web_entrypoint.py -v`

Expected: PASS — and if you added `dialogues` in Step 5, it went red first and
`web.py` needs that line too.

- [ ] **Step 9: All four gates, and the committed console**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `cd frontend && npm run verify`

Run: `git status --porcelain research_team/interfaces/web/static`

Expected: **empty.** No task in this plan touches `frontend/src`, so any drift
here is not yours — investigate before committing it.

- [ ] **Step 10: Commit**

```bash
git add research_team/application/socratic.py research_team/composition.py \
  research_team/interfaces/web/app.py web.py \
  tests/integration/test_socratic_attempts.py
git commit -m "Mark answers inside a dialogue, and let them count

Two writes per attempt, and the second is why this is a method on the socratic
service rather than a call to SessionService.record_attempt. The first is the
ordinary progress attempt. The second is a SocraticProgressObserved with
evidence='attempt' on the dialogue's own stream, which is what lets a stopping
condition be met by something the reader DID rather than by the model's opinion
of what they said. Without it, grading here is grading in an ask: a verdict
shown and forgotten.

Progress keys on the dialogue id. That is the design's §3 and it answers B33
for this surface only: a dialogue has a durable id, survives eviction, and
means exactly one reader working toward one goal, which is what LearnerProgress
needs and an ask has neither half of. Nothing about the ask changes.

path is turn/{position} because LearnerProgress.decide refuses an empty path
and a dialogue has no file. The progress id is already the dialogue, so what
path disambiguates is which exchange.

Which makes position half a grading key, and that is where the formula bug
Plan 1 fixed becomes visible to a reader. len(messages) // 2 and
(len - 1) // 2 agree on every odd history -- every dialogue with an opening
question -- and differ only when _resume finds an empty opening_prompt, which
SocraticDialogueStarted permits and older streams produce. With the wrong one,
exchange 1 of such a dialogue is numbered 0, collides with exchange 0, and the
reader is marked against a component they were never shown. The test is
parametrised over both parities and proved red on the empty one alone: the odd
case passes under either formula, which is how the wrong one survived review.

A wrong answer is recorded too. A stopping condition fed only by correct
attempts is fed by a biased sample of what the reader actually did.

The observation is written before the progress attempt, so a failure between
them leaves the dialogue knowing something happened rather than a progress row
nothing points at."
```

---

## Self-review

**Spec coverage — Plan 2's share.**

| Spec | Where |
| --- | --- |
| §4 the prompt is a parameter; a second executor costs one constructor argument | Task 3 |
| §4 compose the socratic prompt; do **not** concatenate onto `ASK_PROMPT` | Task 2, with a prove-it-red step |
| §4 components a dialogue may author are a decision, not an inheritance; `mcq`/`cloze` first | Task 1 |
| §4 the tool allowlist is not injectable and is therefore scope | Task 3 reuses `READ_ONLY_TOOLS` unchanged via `readable`; nothing in this plan widens it |
| §4 composition is single-instance; a second executor is a few lines plus a `create_app` parameter | Tasks 3 and 4 |
| §4 no langgraph memory; dialogue state lives in the aggregate | Task 3 — no checkpointer, framing passed per call |
| §3 progress keys on the dialogue id; `mcq`/`cloze` gradeable in-dialogue | Task 5 |
| §7 in scope: second executor, route and SSE stream | Tasks 3 and 4 |
| §7 out: changing the tool allowlist, generalising B33, multi-reader, cross-project resumption | untouched by every task; Task 5's docstring states the B33 limit explicitly |
| §5 `SocraticProgressObserved` from the model's own assessment; `SocraticDialogueConcluded` | **NOT COVERED — Plan 4.** See the header section; `evidence="attempt"` observations are covered by Task 5 |
| §9 the four gates plus the fifth | every task; Task 5 Step 9 checks the console tree |
| §9 row-exists assertions rather than "the request succeeded" | Tasks 3, 4, 5 — every persistence assertion reads a row or a stream |
| §5 goal and stopping condition visible to the reader | Task 4's `dialogue` frame carries both; *rendering* is Plan 3 |

**What I could not plan cleanly:**

1. **Nothing concludes a dialogue, and that is now Plan 4 rather than a
   deferral.** `SocraticPrompt.observation` and `.concluded` stay at their
   defaults here, so `SocraticDialogueConcluded` is written by nothing in Plans
   1 or 2 and a dialogue ends only when the reader stops replying — which is the
   thing the spec's first sentence says it must not do. **Ruled: Plan 4,
   "concluding a dialogue", planned after Plan 3**, because it is agent judgement
   rather than frontend work and because its parse fails silently and needs its
   own red proofs rather than riding along at the end of another plan. Made loud
   in three places rather than one: this plan's header section, the executor's
   return comment, and the note there that the `concluded` terminal status is
   consequently unreachable through any live path and is **not** dead code.
2. **Plan 1's Task 5 runs before any task here**, so `dialogues` will already be
   on `create_app` when this plan's Task 5 arrives. The defensive step is kept
   anyway — "add it if absent, say so in the commit" costs nothing and is right
   if the order ever changes — as is the warning to whoever runs second not to
   delete the other's `web.py` line.
3. **`test_a_dialogue_is_composed_with_a_model.py` cannot catch the executor
   being wired with `ASK_PROMPT`**, because a fake model ignores its prompt
   entirely. The prompt tests in Task 2 are the only guard, and they assert on
   string identity rather than on behaviour. The test's own docstring says this
   rather than implying wider coverage — but it means "the composed executor uses
   the right prompt" is verified structurally and never end to end.

**Inline decisions worth knowing:**

- **Two assembled prompts, not one.** `frame` and `respond` are different calls;
  one prompt for both invites the model to re-decide the goal every turn, and a
  goal the model can revise is not a stopping condition anything can test. The
  framing prompt gets no component reference.
- **`parse_framing` is module-level and refuses rather than defaults.** A
  `.get(key, "")` implementation is shorter and produces a dialogue that can
  never stop. Being module-level is what makes the refusal testable without a
  model call.
- **`frame` reports no activity.** It is one short call before the reader has
  seen anything; tool chatter under a spinner that has not yet said what the
  dialogue is for reads as noise.
- **Starting a dialogue is a plain POST, not a stream** — three strings and no
  activity worth watching.
- **The final SSE frame is typed `prompt`, not `answer`**, and `_socratic_frame`
  is a separate function from `_ask_frame` rather than a branch. A page reusing
  the ask's handler would draw the dialogue's question in the reader's column,
  and it would render.
- **A botched framing is 502, not 400.** The request was fine; the upstream was
  not.
- **`progress` is optional on the service, `read_model` is required.** A build
  without progress grades and forgets, which a reader survives; a build without a
  read model resumes wrongly, which they do not. Both checked with `is not None`.
- **The dialogue observation is written before the progress attempt**, so a
  failure between them leaves the dialogue knowing something happened rather than
  an orphan progress row.
- **A wrong answer is observed too** — a stopping condition fed only by correct
  attempts is fed by a biased sample.

**Placeholder scan.** No "TBD", no "add error handling", no "write tests for the
above", no "similar to Task N". Two steps deliberately say "read the neighbour
and match it": `DeepAgentAskExecutor.run`'s `astream` loop (Task 3 Step 3) and
the `create_app` call sites. Both are structural copies where inventing a second
shape is the risk, and both name the exact method to read.

**Type consistency.** `SocraticFraming`, `SocraticPrompt`, `SocraticObservation`,
`DialogueMessage`, `SocraticDialogueOpened`, `UnknownDialogue`, `DialogueInFlight`
are spelled as Plan 1 landed them — checked against
`research_team/application/socratic.py`, not against Plan 1's text.
`SOCRATIC_COMPONENT_TYPES`, `dialogue_document`, `SOCRATIC_PROMPT`,
`SOCRATIC_FRAMING_SYSTEM`, `parse_framing`, `DeepAgentSocraticExecutor`,
`record_attempt`, `progress_for` are spelled identically across Tasks 1–5 and the
route bodies. The SSE frame keys are listed once, in Task 4's Interfaces block,
and that table is what Plan 3's DTOs are written against. `turn/{position}` is
the same string in `record_attempt`, the route's `item_view` call, and all three
tests that assert on it.
