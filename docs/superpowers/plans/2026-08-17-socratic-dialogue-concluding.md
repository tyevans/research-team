# Socratic Dialogue — Plan 4 of 4: concluding a dialogue

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the headline true. A socratic dialogue should stop when the reader has demonstrated the thing, not when they stop typing — so the model must judge, its judgement must be parseable or refused, and a finished dialogue must read as finished rather than as missing.

**Architecture:** Almost none of this is new machinery. `SocraticDialogueConcluded`, the terminal status, `decide`'s refusals and `_record`'s `if asked.concluded:` branch all exist and are wired; the console already renders the concluded state and swaps out its composer. **The only thing missing is that `DeepAgentSocraticExecutor.respond` always returns `concluded=False, observation=None`.** So this plan is a judgement parse in the shape of `parse_framing`, plus the handful of places that were never reachable while nothing could conclude — and one of those turns out to be a defect this plan *creates*.

**Tech Stack:** Python 3 / deepagents + LangChain (infrastructure only) / PyYAML / FastAPI / `eventsource-py`. One frontend task, in TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-08-17-socratic-dialogue-design.md`

**Predecessors:** Plans 1–3, all merged. `c805ecd` is the tip this plan is written against.

---

## What is already built, verified against the code rather than the plans

`grep` results, not recollection:

| Piece | Where | State |
| --- | --- | --- |
| `SocraticDialogueConcluded` | `socratic_dialogue.py:157` | exists, `reason: ConclusionReason` |
| `ConclusionReason = Literal["met", "abandoned"]` | `:67` | exists; **nothing produces `"abandoned"`** |
| terminal `status`, refusal arms | `decide`, `:275` | exists, ordered so a concluded dialogue says "already concluded" |
| `SocraticProgressObserved(evidence=…)` | `:148` | written on every graded answer, right or wrong |
| `_record` writing the conclusion | `socratic.py:686-689` | **already there** — `if asked.concluded:` → `ConcludeSocraticDialogue(reason="met")` |
| `SocraticPrompt.concluded` / `.observation` | `socratic.py:101-104` | exist at defaults; **the executor never sets either** |
| `post_dialogue_attempt` → 409 | `app.py` | catches `CommandRejectedError`, added for this plan |
| console renders concluded | `DialoguePage.tsx:116` | renders the line, swaps out the composer |

**So the write path is complete and the read path is complete. The judgement is the hole.** One task fills it; the rest of this plan is the consequences of it being filled.

---

## The design question, answered

The lead asked for a recommendation rather than a decision: should the model judge conclusion **every turn**, or should the dialogue **ask explicitly** once recorded evidence suggests the condition is met?

**Option A — judge every turn.** `respond` asks for a judgement alongside the question, in the same fenced block.

- Costs: a judgement on every exchange, in tokens and in a second parse per turn. More importantly, it asks the model to answer two questions at once — "what should I ask next" and "are we done" — and the second reliably contaminates the first. A model that has just written `concluded: false` has committed to continuing and will find something to ask.
- Buys: no second model call ever; nothing has to decide "suggests"; the parse happens where the prose already is.

**Option B — ask explicitly when evidence suggests.** A cheap local predicate over the recorded `SocraticProgressObserved` stream decides when to spend a judgement call.

- Costs: something must define "suggests", and every definition is arbitrary — *n* attempts, *n* correct, any correct. That threshold is a second stopping condition, unwritten and untestable, sitting in front of the one the author wrote down. It is exactly the thing §5 says a stopping condition exists to avoid.
- Buys: fewer judgement calls; the judgement is a focused call with one job.

**Ruled: Option A, with the contamination mitigated by ordering rather than by a second call.** Recommended here and accepted by the lead, whose wording is the one to keep: a threshold defining when evidence "suggests" the condition is met would be **a second stopping condition -- unwritten and untestable -- sitting in front of the one the author wrote down**, and this feature's whole thesis is that a stopping condition decided anywhere but the aggregate is one nothing can test. **A hidden numeric gate in front of it undoes the argument the aggregate exists to make.**

The contamination is real and is handled by **asking for the judgement first in the block and the question second**, so the model commits to the verdict before it writes what to ask — and by allowing an empty `prompt` when concluding, so "nothing further to ask" is expressible rather than something the model has to fabricate. Task 1's prompt does both, and Task 2 has a test that a concluded reply may carry no question.

Requiring a closing question instead would have contradicted `SOCRATIC_METHOD_PROMPT`'s own instruction not to ask one more to be sure -- which is the second half of why the empty prompt is legal rather than a leniency.

The cost that stays: one judgement per exchange. Written down rather than hidden, and cheap relative to the tool calls already in every turn.

---

## Global Constraints

- **Four gates, and passing three is not passing.** `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`.
  The ruff commands run over the whole repository.
- **Only Tasks 5 and 6 touch `frontend/src`.** Each ends with
  `cd frontend && npm run build` and a commit of the rebuilt
  `research_team/interfaces/web/static` — CI compares it and `verify` never does.
  Every other task must leave that tree clean, and Task 6 rebuilds again
  rather than assuming Task 5's build still stands.
- **The parse fails silently, and that is why this is its own plan.** A malformed
  judgement that defaults to "not concluded" looks exactly like a dialogue that
  has not finished yet, indefinitely. **The parser refuses rather than defaults**,
  the way `parse_framing` does, and the refusal is reachable without a model call
  because the parser is module-level.
- **An event no projection handles counts as APPLIED.** Every assertion about
  persistence must be that a row or an event exists with the value it carried,
  never that a request returned 200.
- **Do not add `AskService._record`'s `create_new` fallback.** `_record` loading
  and never creating is a deliberate second line of defence: a fabricated id dies
  at the repository rather than opening a second stream.
- **Never default an optional collaborator with `or` / `||`.** An empty list, an
  empty string and `0` are all falsy and all legitimate.
- **Write tests that can fail.** Six briefs in this sequence carried an assertion
  that could never have passed or a fixture that could not typecheck. Every test
  below names what it is red against; where a test is asserting something already
  true, it says so rather than implying it is a new guarantee.

---

## Rulings this plan makes

**The judgement block's keys are derived from the prompt, not written twice.**
`socratic_agent.py` already does this for framing: `_framing_fields()` reads the
keys out of `SOCRATIC_FRAMING_PROMPT`'s own fenced block, so a rename on either
side cannot produce a parser that refuses every well-formed answer. Task 1 reuses
that function for the judgement block rather than adding a second literal.

**An empty `prompt` is legal only when concluding.** A dialogue that has finished
has nothing further to ask, and forcing the model to invent a closing question is
how a dialogue asks one more "to be sure" — which `SOCRATIC_METHOD_PROMPT`
already tells it not to do. A blank prompt on a *non*-concluding turn is a
refusal, because that is a model that produced no question at all.

**`reason="met"` is what the model's judgement writes; `"abandoned"` is the
reader's, and nothing else produces it.** Who ends a dialogue the reader has
given up on had two candidate answers -- the reader explicitly, or a sweep over
stale ones -- and the sweep is refused for this plan's own reason: it needs a
threshold over how long a reader has been away, which is the same arbitrary
number the design section above rejects for deciding conclusion, applied to
attention instead of understanding. Rejecting it there and accepting it here
would be incoherent.

So Task 6 gives the reader the action and nothing sweeps. Leaving the category
half-empty was the alternative and it is the worst of both: this plan exists to
remove an enum branch nothing can reach, and it would have shipped removing one
and leaving its twin -- after real effort was spent keeping those branches from
being tidied away as dead code.

**Frame it as ending a dialogue, not abandoning one.** `reason="abandoned"` stays
the stored value, because it is accurate about *why* it ended, but nothing the
reader sees calls them a quitter. A reader who wants to stop should be able to;
the alternative is a conversation with no way to close it, which is a worse
experience than the one this plan is fixing.

**This plan creates a defect and fixes it in the same slice.** `_resume` refuses
a concluded dialogue with `UnknownDialogue`, which `reply_to_dialogue` turns into
**404 "no dialogue … in project"**. That branch has never fired, because nothing
could conclude. The moment Task 2 lands, a reader who refreshes a finished
dialogue and types gets told it does not exist — when it exists and it finished.
Task 3 separates the two.

---

## File structure

| File | Responsibility |
| --- | --- |
| `research_team/infrastructure/agent/socratic_agent.py` | the judgement block in the prompt, `parse_judgement`, `respond` returning it |
| `tests/infrastructure/test_socratic_agent.py` | the parse, refusing rather than defaulting |
| `tests/integration/test_a_dialogue_concludes.py` | the composed path: a model that concludes ends the dialogue |
| `research_team/application/socratic.py` | `DialogueConcluded` split out of `UnknownDialogue`, and `end` — the reader's own conclusion |
| `research_team/interfaces/web/app.py` | 409 for a concluded dialogue rather than 404, and the route that ends one |
| `tests/integration/test_socratic_stream.py` | the new status, and ending |
| `frontend/src/...dialogue/` | the finished state on a resumed dialogue, and the button that ends one |
| `BACKLOG.md` | the idle sweep, and what Task 3 leaves |

---

### Task 1: Ask the model for a judgement, and refuse a bad one

**Files:**
- Modify: `research_team/infrastructure/agent/socratic_agent.py`
- Modify: `tests/infrastructure/test_socratic_agent.py`

**Interfaces:**
- Consumes: `_FENCE`, `_YAML_LOADER`, `_framing_fields`-style derivation,
  `SocraticObservation`, `SocraticPrompt`, `EvidenceKind`.
- Produces:

```python
SOCRATIC_JUDGEMENT_PROMPT: str      # appended into SOCRATIC_PROMPT
_JUDGEMENT_FIELDS: tuple[str, ...]  # derived from the block above

@dataclass(frozen=True)
class SocraticJudgement:
    concluded: bool
    prompt: str
    observation: SocraticObservation | None

def parse_judgement(text: str) -> SocraticJudgement: ...
```

  `parse_judgement` is module-level for `parse_framing`'s reason: the refusal
  must be reachable without a model call, and a private method would put every
  case behind a fake chat model.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_socratic_agent.py`:

```python
from research_team.infrastructure.agent.socratic_agent import (
    SOCRATIC_JUDGEMENT_PROMPT,
    parse_judgement,
)


def test_a_judgement_block_becomes_a_verdict_and_a_question():
    """The ordinary turn: not finished, here is the next question.

    The judgement comes FIRST in the block and the question second, which is
    the ordering ruling -- a model that has already written `concluded: false`
    has committed to continuing before it writes what to ask. Asked the other
    way round it writes a question and then rationalises a verdict that keeps
    it.
    """
    text = (
        "```yaml\n"
        "concluded: false\n"
        "observation: |\n"
        "  named both parties but not what divided them\n"
        "prompt: |\n"
        "  What did Arius actually claim about the Son?\n"
        "```\n"
    )

    judged = parse_judgement(text)

    assert judged.concluded is False
    assert judged.prompt == "What did Arius actually claim about the Son?"
    assert judged.observation is not None
    assert judged.observation.observation == "named both parties but not what divided them"
    # The model's own reading, never a graded fact. A stopping condition met
    # entirely by these is a dialogue that graded its own homework, and the kind
    # is the only thing that keeps that visible.
    assert judged.observation.evidence == "assessment"


def test_a_concluding_judgement_may_carry_no_question():
    """A finished dialogue has nothing further to ask.

    Forcing a closing question is how a dialogue asks one more "to be sure",
    which `SOCRATIC_METHOD_PROMPT` already tells the model not to do. Red
    against a parser that requires `prompt` unconditionally -- every genuine
    conclusion would then be refused, and a dialogue that can never conclude is
    exactly what this plan exists to end.
    """
    text = (
        "```yaml\n"
        "concluded: true\n"
        "observation: |\n"
        "  distinguished the settlement from the politics, unaided\n"
        "prompt: \"\"\n"
        "```\n"
    )

    judged = parse_judgement(text)

    assert judged.concluded is True
    assert judged.prompt == ""
    assert judged.observation is not None


def test_a_turn_that_concludes_nothing_and_asks_nothing_is_refused():
    """The silent failure this plan is shaped around, in its purest form.

    An empty prompt on a non-concluding turn is a model that produced no
    question. Defaulted, the reader sees a blank utterance and a dialogue that
    is somehow still going; refused, the turn fails and says why.

    Red against a parser that only requires `prompt` when `concluded` is false
    *and* treats a missing key as empty -- the common shape.
    """
    text = "```yaml\nconcluded: false\nprompt: \"\"\n```\n"

    with pytest.raises(ValueError, match="question"):
        parse_judgement(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "That's exactly right, well done!",
        "```yaml\nprompt: What next?\n```\n",
        "```yaml\nconcluded: maybe\nprompt: What next?\n```\n",
        "```yaml\n- concluded\n- prompt\n```\n",
    ],
)
def test_a_judgement_that_cannot_be_read_is_refused_rather_than_defaulted(text):
    """**The whole reason this is its own plan.**

    Every case here defaults, under a `.get(key, False)` implementation, to
    `concluded: False` -- which is indistinguishable from a dialogue that is
    simply still going. A broken judgement path would then look like working
    software forever: the reader keeps answering, the model keeps asking, and
    nothing ever stops. Refusing makes the turn fail loudly on the first
    malformed answer.

    The prose case is the one that matters most: a model that ignored the
    format entirely and just replied warmly is the likeliest real failure, and
    it is the one a truthy-`.get` reads as "not finished, no question".

    `concluded: maybe` is here because YAML will happily give back the string
    `"maybe"`, which is truthy -- a parser doing `bool(loaded.get("concluded"))`
    concludes the dialogue on a value the model never meant as a yes.
    """
    with pytest.raises(ValueError, match="judgement"):
        parse_judgement(text)


def test_the_parser_asks_for_exactly_the_keys_the_judgement_prompt_asks_for():
    """Derived, not written twice -- the same guard `_framing_fields` gives the
    framing parse. Two independent literals produce either a parser that
    refuses every well-formed judgement (a renamed key it still demands) or one
    that reads a key nothing sends, and neither has a symptom a caller could
    act on.
    """
    from research_team.infrastructure.agent.socratic_agent import _JUDGEMENT_FIELDS

    assert set(_JUDGEMENT_FIELDS) == {"concluded", "observation", "prompt"}
    for name in _JUDGEMENT_FIELDS:
        assert f"{name}:" in SOCRATIC_JUDGEMENT_PROMPT


def test_an_observation_is_optional_and_absent_means_nothing_was_demonstrated():
    """The one key that may be absent, and the asymmetry is deliberate: a turn
    where the reader demonstrated nothing worth recording is ordinary, where a
    turn with no verdict and no question is broken.

    Red against a parser that manufactures an empty observation, which would
    write a `SocraticProgressObserved` carrying no observation on every turn and
    bury the real ones.
    """
    judged = parse_judgement("```yaml\nconcluded: false\nprompt: Why?\n```\n")

    assert judged.observation is None
    assert judged.prompt == "Why?"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/infrastructure/test_socratic_agent.py -x -k judgement`

Expected: FAIL — `ImportError: cannot import name 'parse_judgement'`.

- [ ] **Step 3: Add the prompt block**

Append `SOCRATIC_JUDGEMENT_PROMPT` and fold it into `SOCRATIC_PROMPT`. Note the
key order in the fenced block — the derivation reads it, and the model answers in
the order it is shown:

```python
SOCRATIC_JUDGEMENT_PROMPT = """
## Saying whether this is finished

Answer every turn as YAML, and nothing else:

```yaml
concluded: false
observation: |
  What the reader demonstrated this turn, if anything. Omit the key entirely
  when they demonstrated nothing worth recording -- most turns.
prompt: |
  Your one question. Leave it empty ONLY when concluded is true.
```

**Decide `concluded` before you write the question.** The order is not
cosmetic: a verdict written after a question is a verdict chosen to justify
asking it, and this dialogue stops when the reader has demonstrated the thing
rather than when you run out of questions.

`concluded: true` means the stopping condition you were given is met -- not
that the reader is doing well, and not that you have run out of things to ask.
When it is true, leave `prompt` empty. There is nothing further to ask, and
asking one more to be sure is the thing you were told not to do.

`observation` is your reading of what they showed, which is weaker evidence
than a marked answer and is recorded as such. Write it when they demonstrated
something specific; omit it otherwise. "Engaged well" is not an observation.
"""

SOCRATIC_PROMPT = (
    SOCRATIC_TOOLS_PROMPT
    + SOCRATIC_METHOD_PROMPT
    + SOCRATIC_COMPONENT_PROMPT
    + SOCRATIC_JUDGEMENT_PROMPT
)
```

- [ ] **Step 4: Add the derivation and the parser**

Reuse the existing `_framing_fields` shape. Extract the common half rather than
copying it — one function taking a prompt string, called twice:

```python
def _declared_fields(prompt: str) -> tuple[str, ...]:
    """The keys a prompt's own fenced block asks the model for.

    Was `_framing_fields`, taking no argument and closing over
    `SOCRATIC_FRAMING_PROMPT`. Generalised to a parameter when the judgement
    block needed the identical guard: a second copy would be a second place for
    the derivation to stop matching its prompt, which is precisely the failure
    the derivation exists to prevent.

    Returns `()` rather than guessing if the block stops being a YAML mapping.
    Both callers' `test_the_parser_asks_for_exactly_the_keys_…` fail loudly in
    that case, which is better than a parser that demands nothing.
    """
    fenced = _FENCE.search(prompt)
    if fenced is None:
        return ()
    block = yaml.load(fenced.group(1), Loader=_YAML_LOADER)
    return tuple(block) if isinstance(block, dict) else ()


_FRAMING_FIELDS = _declared_fields(SOCRATIC_FRAMING_PROMPT)
_JUDGEMENT_FIELDS = _declared_fields(SOCRATIC_JUDGEMENT_PROMPT)
```

Then:

```python
@dataclass(frozen=True)
class SocraticJudgement:
    """What one turn's model call decided, parsed."""

    concluded: bool
    prompt: str
    observation: SocraticObservation | None = None


def parse_judgement(text: str) -> SocraticJudgement:
    """A verdict and a question, or a refusal.

    **Refused rather than defaulted, and unlike `parse_framing` the reason is
    not that the failure is expensive -- it is that the failure is silent.** A
    `.get("concluded", False)` implementation reads a model's warm prose reply,
    or a dropped fence, or a mistyped key, as "not finished". The dialogue then
    runs forever: the reader keeps answering, the model keeps asking, and
    nothing anywhere raises. There is no symptom to notice and no log line to
    find. That is the failure mode this whole plan is shaped around.

    `concluded` must be a real bool. YAML gives back `"maybe"` as a string,
    which is truthy, so `bool(loaded.get("concluded"))` ends dialogues on
    values the model never meant as a yes.

    `prompt` is required except when concluding: a finished dialogue has
    nothing further to ask, and forcing a closing question is how it asks one
    more to be sure.

    `observation` is the one optional key. A turn where the reader demonstrated
    nothing is ordinary; manufacturing an empty observation for it would write a
    `SocraticProgressObserved` per turn and bury the real ones.
    """
    fenced = _FENCE.search(text)
    body = fenced.group(1) if fenced else text
    try:
        loaded = yaml.load(body, Loader=_YAML_LOADER)
    except yaml.YAMLError as error:
        raise ValueError(f"the judgement did not parse as YAML: {error}") from error
    if not isinstance(loaded, dict):
        raise ValueError(
            f"the judgement was not a mapping, got {type(loaded).__name__}"
        )
    concluded = loaded.get("concluded")
    if not isinstance(concluded, bool):
        raise ValueError(f"the judgement's `concluded` was not true or false, got {concluded!r}")
    prompt = str(loaded.get("prompt") or "").strip()
    if not prompt and not concluded:
        raise ValueError("the judgement carries no question and did not conclude")
    observed = loaded.get("observation")
    observation = (
        SocraticObservation(observation=str(observed).strip(), evidence="assessment")
        if isinstance(observed, str) and observed.strip()
        else None
    )
    return SocraticJudgement(concluded=concluded, prompt=prompt, observation=observation)
```

Note the two error strings: every refusal says "judgement" except the
no-question one, which says "question". The tests match on those substrings, so
a rewording that collapsed them would make one test pass for the wrong reason.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/infrastructure/test_socratic_agent.py -v`

Expected: PASS — the new judgement tests and every framing test, which must be
unaffected by `_framing_fields` becoming `_declared_fields(...)`.

- [ ] **Step 6: Prove the refusal red**

Replace the `concluded` check with the defaulting version:

```python
    concluded = bool(loaded.get("concluded", False))
```

Re-run. Expected: `test_a_judgement_that_cannot_be_read_is_refused_rather_than_defaulted`
fails on **all five** parametrised cases, each returning a `SocraticJudgement`
rather than raising — and note that under that version the prose case yields
`concluded=False` with an empty prompt, which is the exact shape a dialogue that
never ends is made of. Revert.

- [ ] **Step 7: Wiring**

Run: `uv run pytest tests/test_architecture.py -v`

Expected: PASS. `socratic_agent.py` is infrastructure and may import LangChain;
`SocraticJudgement` returns `SocraticObservation`, which is an application type,
and importing *down* is allowed.

Nothing calls `parse_judgement` yet — Task 2 does. Confirm:

Run: `grep -rn "parse_judgement" research_team/`

Expected: only its definition.

- [ ] **Step 8: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 9: Commit**

```bash
git add research_team/infrastructure/agent/socratic_agent.py \
  tests/infrastructure/test_socratic_agent.py
git commit -m "Ask the model whether the dialogue is finished, and refuse a bad answer

The judgement is asked for on every turn rather than gated behind a predicate
over recorded evidence. The gate was the alternative and it is worse: something
would have to define when evidence 'suggests' the condition is met, every
definition is arbitrary, and that threshold would be a second stopping
condition -- unwritten, untestable, sitting in front of the one the author
wrote down. This feature's whole thesis is that a stopping condition decided
anywhere but the aggregate is one nothing can test.

The cost of asking every turn is that the model answers two questions at once
and the second contaminates the first: having written a question, it picks the
verdict that justifies asking it. Handled by ordering rather than by a second
call -- concluded comes first in the block, so the verdict is committed before
the question exists -- and by allowing an empty prompt when concluding, so
'nothing further to ask' is expressible instead of fabricated.

The parser refuses rather than defaults, and unlike parse_framing the reason is
not that the failure is expensive but that it is SILENT. A .get('concluded',
False) reads warm prose, a dropped fence or a mistyped key as 'not finished',
and the dialogue then runs forever with nothing raising anywhere. Proved by
writing the defaulting version: all five malformed cases come back as verdicts,
and the prose one comes back as exactly the shape a dialogue that never ends is
made of.

concluded must be a real bool. YAML returns 'maybe' as a truthy string, so
bool(loaded.get(...)) ends dialogues on values the model never meant as a yes.

_framing_fields became _declared_fields(prompt). The judgement block needed the
identical guard, and a second copy would be a second place for a derivation to
stop matching the prompt it derives from -- which is the failure the derivation
exists to prevent."
```

---

### Task 2: Let the executor return it, and watch a dialogue end

**Files:**
- Modify: `research_team/infrastructure/agent/socratic_agent.py` (`respond`)
- Create: `tests/integration/test_a_dialogue_concludes.py`

**Interfaces:**
- Consumes: Task 1's `parse_judgement`; `SocraticPrompt`, `citations`, `last_text`.
- Produces: `respond` returning `SocraticPrompt(prompt=…, observation=…,
  concluded=…, citations=…)` — the same type, with two fields that were always
  defaults now carrying values. **No signature changes anywhere**, which is why
  `_record` needs no edit at all.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_a_dialogue_concludes.py`:

```python
"""A dialogue that ends, over the composed application.

The write path has existed since Plan 2 -- `_record` has always had
`if asked.concluded:` -- and has never once fired, because the executor
returned the default. So every assertion here is on a stored event: a green
call proves nothing, and "the endpoint answered" is compatible with the branch
still being dead.
"""

from uuid import UUID, uuid4

import pytest
from eventsource import StreamId, collect
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.composition import build_application
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticDialogueConcluded,
    SocraticProgressObserved,
    SocraticTurnRecorded,
)
from research_team.interfaces.web import create_app

FRAMING = AIMessage(
    content=(
        "```yaml\ngoal: |\n  understand the settlement\n"
        "stopping_condition: |\n  the reader separates it from the politics\n"
        "opening_prompt: |\n  What do you think it settled?\n```\n"
    )
)
CONTINUING = AIMessage(
    content=(
        "```yaml\nconcluded: false\nobservation: |\n  named both parties\n"
        "prompt: |\n  What divided them?\n```\n"
    )
)
CONCLUDING = AIMessage(
    content=(
        "```yaml\nconcluded: true\nobservation: |\n"
        "  separated the settlement from the politics, unaided\nprompt: \"\"\n```\n"
    )
)


async def _application(tmp_path, responses):
    application = build_application(
        model=FakeMessagesListChatModel(responses=responses),
        db_path=str(tmp_path / "concluding.db"),
    )
    await application.start()
    return application


async def _project(application) -> UUID:
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
        assert created.status_code == 200
        return UUID(created.json()["id"])


async def _events(application, dialogue_id):
    stream = StreamId(dialogue_id, SocraticDialogue.aggregate_type)
    return [
        envelope.event
        for envelope in await collect(
            application.socratic._transcripts.event_store.read_stream(stream)
        )
    ]


async def test_a_dialogue_the_model_concludes_is_concluded_on_its_stream(tmp_path):
    """The headline, as a stored fact.

    Red against the executor as it shipped in Plan 2: `concluded` is the
    default `False`, `_record`'s branch never fires, and the stream ends on a
    turn. Nothing raises in that build -- the request succeeds and the reader
    is simply asked another question forever -- which is why this asserts on
    the event list and not on a status code.
    """
    application = await _application(tmp_path, [FRAMING, CONCLUDING])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It was about the politics."
        ):
            pass

        events = await _events(application, dialogue_id)
        assert [type(event) for event in events][-1] is SocraticDialogueConcluded
        assert events[-1].reason == "met"
    finally:
        await application.close()


async def test_the_model_s_own_reading_is_recorded_as_an_assessment(tmp_path):
    """The second half of a judgement, and the half that keeps the evidence
    honest. `evidence="assessment"` and never `"attempt"`: this is the model's
    opinion of prose, which is weaker than a marked answer, and a stopping
    condition met entirely by these is a dialogue that graded its own homework.

    Red against a `respond` that returns `concluded` and drops `observation` --
    the dialogue would end with no record of what it ended on.
    """
    application = await _application(tmp_path, [FRAMING, CONTINUING])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="Arius and Athanasius."
        ):
            pass

        events = await _events(application, dialogue_id)
        observed = [e for e in events if isinstance(e, SocraticProgressObserved)]
        assert len(observed) == 1
        assert observed[0].observation == "named both parties"
        assert observed[0].evidence == "assessment"
        # And the turn is still recorded, in the order `_record` writes them.
        assert [type(e) for e in events[1:]] == [
            SocraticTurnRecorded,
            SocraticProgressObserved,
        ]
    finally:
        await application.close()


async def test_a_concluding_turn_records_its_empty_question_rather_than_inventing_one(
    tmp_path,
):
    """A finished dialogue has nothing further to ask, so the last turn's
    `prompt` is empty and `pending_prompt` clears with it.

    Red against an executor that falls back to `last_text(final)` when the
    parsed prompt is empty: the reader would be shown the raw YAML block as the
    dialogue's closing question.
    """
    application = await _application(tmp_path, [FRAMING, CONCLUDING])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It separated them."
        ):
            pass
        await application.dialogues.caught_up()

        turns = await application.dialogues.turns_for(dialogue_id)
        assert turns[-1].prompt == ""
        row = await application.dialogues.get(dialogue_id)
        assert row.status == "concluded"
        assert row.concluded_reason == "met"
        assert row.pending_prompt == ""
    finally:
        await application.close()


async def test_a_reply_to_a_concluded_dialogue_is_refused_before_the_model_is_called(
    tmp_path,
):
    """`_resume`'s third refusal, reachable for the first time.

    It has been in the code since Plan 1 and has never fired, because nothing
    could conclude a dialogue. `decide` would refuse the turn anyway -- but only
    after the model had been called and paid for, which is the whole reason the
    check is in `_resume`.

    The model list has exactly two responses, so a build that reached the
    executor raises `IndexError` from the fake rather than the refusal below.
    That is the assertion doing work: it distinguishes "refused" from "answered
    a third time".
    """
    from research_team.application.socratic import UnknownDialogue

    application = await _application(tmp_path, [FRAMING, CONCLUDING])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It separated them."
        ):
            pass
        application.socratic.forget(dialogue_id)
        await application.dialogues.caught_up()

        with pytest.raises(UnknownDialogue, match="concluded"):
            async for _note in application.socratic.respond(
                project_id=project_id, dialogue_id=dialogue_id, reply="one more?"
            ):
                pass
    finally:
        await application.close()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/integration/test_a_dialogue_concludes.py -x`

Expected: FAIL — the first test's last event is a `SocraticTurnRecorded`, because
`respond` still returns the default `concluded=False`. **Note that nothing
raises**: that is the shape of the bug this plan closes.

- [ ] **Step 3: Return the judgement**

In `respond`, replace the `SocraticPrompt(...)` construction. The whole comment
block about Plan 4 owning `observation` and `concluded` goes with it:

```python
        judged = parse_judgement(last_text(final))
        return SocraticPrompt(
            # The parsed question, never `last_text(final)`. The model's last
            # message is the YAML block; falling back to it when the parse
            # yields an empty prompt -- which a concluding turn does by design
            # -- would show the reader the block as the dialogue's closing
            # words.
            prompt=judged.prompt,
            citations=citations(final),
            observation=judged.observation,
            concluded=judged.concluded,
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/integration/test_a_dialogue_concludes.py -v`

Expected: PASS, 4 tests.

- [ ] **Step 5: Run the whole socratic suite**

Run: `uv run pytest tests/ -k socratic -v`

Expected: PASS. Plan 2's and Plan 3's tests use stub executors and are unaffected
— **except any that drive the real executor with a fake model**, which now must
answer in the judgement format. If one fails, its fixture's `AIMessage` needs the
block; that is a real consequence of this change and not a broken test.

- [ ] **Step 6: Wiring**

| Link | Where | Confirm |
| --- | --- | --- |
| prompt asks for it | `SOCRATIC_JUDGEMENT_PROMPT` in `SOCRATIC_PROMPT` | Task 1 |
| parse | `parse_judgement` | called in `respond` |
| carried | `SocraticPrompt.concluded` / `.observation` | set, not defaulted |
| written | `_record`'s `if asked.concluded:` | **unchanged** — already there |
| projected | `SocraticDialogueRow.status` | `concluded` |
| refused after | `_resume`'s third check | now reachable |

Run: `grep -n "concluded" research_team/application/socratic.py`

Expected: `_record`'s branch, unedited. If this task changed it, something is
wrong — the write path was complete before this plan started.

- [ ] **Step 7: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 8: Commit**

```bash
git add research_team/infrastructure/agent/socratic_agent.py \
  tests/integration/test_a_dialogue_concludes.py
git commit -m "Let a dialogue end when the reader has demonstrated the thing

Four lines in respond, and the feature's headline becomes true. Everything else
was already built and had never once run: _record has had its
if asked.concluded branch since Plan 2, the terminal status and its refusals
since Plan 1, and the console renders the finished state. The executor returned
the default on every turn, so all of it was dead.

Which is why every assertion here is on a stored event. In the build this
replaces, nothing raises and no request fails -- the reader is simply asked
another question forever -- so a test on a status code passes against exactly
the bug.

prompt comes from the parse and never from last_text(final). The model's last
message is the YAML block, and falling back to it when the parsed prompt is
empty -- which a concluding turn produces by design -- would show the reader
the block as the dialogue's closing words.

The model's own reading is recorded as evidence='assessment', never 'attempt'.
It is an opinion about prose, weaker than a marked answer, and keeping the
kinds apart is what stops a stopping condition met entirely by opinions from
looking like one met by evidence.

_resume's third refusal fires for the first time. It has been in the code since
Plan 1 and could not be reached; decide would have refused the turn anyway, but
only after the model had been called and paid for."
```

---

### Task 3: A finished dialogue is finished, not missing

**Files:**
- Modify: `research_team/application/socratic.py` — `DialogueConcluded`
- Modify: `research_team/interfaces/web/app.py` — the new status
- Modify: `tests/integration/test_socratic_stream.py`

**Interfaces:**
- Produces:

```python
class DialogueConcluded(UnknownDialogue):
    """This dialogue exists, belongs to this project, and has finished."""
```

  A **subclass**, so every existing `except UnknownDialogue` keeps catching it and
  no call site is silently changed by this task. The route catches the narrower
  one first.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_socratic_stream.py`:

```python
async def test_replying_to_a_concluded_dialogue_says_it_finished_not_that_it_is_missing(
    client,
):
    """A defect this feature *creates*, fixed in the slice that creates it.

    `_resume` raises `UnknownDialogue` for a concluded dialogue and the route
    turns that into 404 "no dialogue … in project". That branch could not fire
    before Plan 4 -- nothing could conclude -- so the wrong status was free.

    It is not free now. A reader who finishes a dialogue, refreshes, and types
    is told it does not exist, when it exists and it finished. 404 and 409 are
    a character apart in a log and say opposite things about whether the
    reader's own history is still there.

    409 rather than 410: the dialogue is not gone, it is in a state that
    refuses this request -- the same status `post_dialogue_attempt` already
    answers for an attempt against a concluded dialogue, so the page has one
    rule for both.

    Red against the route as it stands: this comes back 404.
    """
    http, application, stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]
    stub.prompts = [SocraticPrompt(prompt="", concluded=True)]
    await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "done"}
    )
    application.socratic.forget(UUID(dialogue_id))
    await application.dialogues.caught_up()

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "more?"}
    )

    assert response.status_code == 409, response.text
    assert "concluded" in response.json()["detail"]


async def test_an_unknown_dialogue_is_still_a_404(client):
    """The other half, so the split above cannot be implemented by turning
    every refusal into a 409. A guessed id must still be indistinguishable from
    another project's.
    """
    http, _application, _stub = client
    project_id = await _project(http)

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{uuid4()}/reply", json={"reply": "hello?"}
    )

    assert response.status_code == 404, response.text
```

The `client` fixture's stub needs a settable `prompts`; adjust it if it is not
already, and say in the commit that the fixture changed.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_socratic_stream.py -x -k concluded`

Expected: FAIL — 404 where 409 is asserted.

- [ ] **Step 3: Split the exception and catch it first**

In `socratic.py`, add the subclass beneath `UnknownDialogue` and raise it from
`_resume`'s concluded branch, with the docstring explaining why it is a subclass.
Extend `UnknownDialogue`'s own docstring, which currently says the three cases
are one exception because a caller has the same move for all three — that is no
longer true of the third.

In `app.py`, catch `DialogueConcluded` **before** `UnknownDialogue`. `reply_to_dialogue`'s
docstring currently says the 404 "covers a guessed id, a stale one, and a
concluded one. All 404: telling a caller that an id they cannot use does exist is
the distinction not worth drawing." That sentence is what this task overturns --
rewrite it rather than leaving a comment that argues against the code beneath it,
and say why the distinction is now worth drawing (a concluded dialogue is the
reader's *own*, and its history is still there).

```python
        except DialogueConcluded as finished:
            # 409 and not 404: the dialogue exists and belongs to this reader,
            # and it is in a state that refuses this request. The same status
            # `post_dialogue_attempt` answers for an attempt against a concluded
            # dialogue, so a page has one rule for both.
            #
            # Ordered above `UnknownDialogue` because it is a subclass -- the
            # broader arm would otherwise swallow it and this reads as working.
            raise HTTPException(status_code=409, detail=str(finished)) from finished
        except UnknownDialogue as missing:
            ...
```

- [ ] **Step 4: Run to verify both pass**

Run: `uv run pytest tests/integration/test_socratic_stream.py -v`

Expected: PASS.

- [ ] **Step 5: Prove the ordering matters**

Swap the two `except` arms so `UnknownDialogue` comes first. Re-run. Expected:
the 409 test fails with 404 — because `DialogueConcluded` is a subclass and the
broader arm catches it. Restore.

That is the finding worth recording: the subclass keeps every existing caller
working *and* makes arm order load-bearing, which is a trade rather than a free
win.

- [ ] **Step 6: Wiring**

Run: `grep -rn "UnknownDialogue" research_team/ tests/`

Every existing catcher must still be correct: a subclass means they all keep
catching, which is the point. Confirm none of them needed the narrower case and
was silently getting it.

- [ ] **Step 7: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 8: Commit**

```bash
git add research_team/application/socratic.py research_team/interfaces/web/app.py \
  tests/integration/test_socratic_stream.py
git commit -m "Say a dialogue finished rather than that it is missing

A defect this feature creates, fixed in the slice that creates it. _resume has
always raised UnknownDialogue for a concluded dialogue and the route has always
turned that into 404 'no dialogue in project'. The branch could not fire while
nothing could conclude, so the wrong status cost nothing.

It costs something now. A reader who finishes a dialogue, refreshes and types
is told it does not exist -- when it exists, it finished, and their whole
history is still there. 404 and 409 are a character apart in a log and say
opposite things about whether that history survived.

409 and not 410: the dialogue is not gone, it is in a state that refuses this
request, which is the same status post_dialogue_attempt already answers for an
attempt against a concluded dialogue. One rule for both.

DialogueConcluded subclasses UnknownDialogue so every existing except keeps
catching it and no call site changes silently. The cost is that arm order in
the route is now load-bearing -- proved by swapping them, which turns the 409
back into a 404 -- and that is a trade rather than a free win."
```

---

### Task 4: File what conclusion does not yet cover

**Files:**
- Modify: `BACKLOG.md`

No code. This task exists because Plan 4 removes one unreachable branch and
leaves two others, and an unwritten gap in a feature that now claims to be
complete is worse than the same gap in one that admits it is not.

- [ ] **Step 1: File the idle sweep, and say why it is not here**

Task 6 gives `"abandoned"` a producer, so what is left to file is the *other*
candidate surface: a sweep that ends dialogues idle past some threshold. Write
the entry with what exists after this plan (the reason, the event, the terminal
status, the projection column, and a reader action that reaches all four), what
is missing (nothing ends a dialogue the reader simply walked away from), and why
this plan refused it — the threshold is the same arbitrary number the design
section rejects for deciding conclusion, applied to the reader's attention
instead of their understanding, and a stopping condition decided outside the
aggregate is one nothing can test. It needs its own brief.

Also record the cost of *not* having it: a walked-away dialogue stays `started`
forever, so any future count of "dialogues in progress" is an over-count with no
upper bound.

- [ ] **Step 2: File the concluded-dialogue console gap, against B120**

B120 already records that a resumed dialogue comes back without its conversation.
Add a line to it: **once a dialogue can conclude, that gap acquires a second
symptom.** A reader returning to a finished dialogue now gets an empty thread
*and* a composer, and their first reply is answered 409 by Task 3 rather than
404 — better, but still a page that offers an action it cannot perform. The
console reads `concluded` off the newest turn in the transcript
(`DialoguePage.tsx:72`), and a resumed dialogue has no turns, so it cannot know.
The fix is the same one B120 already names — a port that reads one dialogue whole
— plus reading `status` from that response rather than from the transcript.

- [ ] **Step 3: Note what the reader-ended case leaves unread**

Task 6 stores `reason="abandoned"`, and no read route distinguishes it from
`"met"` — `_dialogue_view` carries `status`, not the reason. A reader returning
to a dialogue they ended is told it reached its goal. Small, and worth the line:
it is the same shape as B120 (a fact that is true in storage and unreadable in
the browser), and Task 6's own scope note says so rather than pretending the
console covers it.

- [ ] **Step 4: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

(`BACKLOG.md` is not linted, but the gates are cheap and this is the task most
likely to be run alone.)

- [ ] **Step 5: Commit**

```bash
git add BACKLOG.md
git commit -m "File what concluding a dialogue still does not cover

Two gaps left after this plan, neither of them an unreachable enum branch --
Task 6 closed the last of those.

The idle sweep is the surface refused rather than deferred by accident. A
dialogue can now end because the reader demonstrated the thing, or because the
reader said stop; it cannot end because they walked away. That needs a threshold
over how long is long enough, which is the same arbitrary number the design
section refused for deciding conclusion, applied to the reader's attention
instead of their understanding -- and a stopping condition decided outside the
aggregate is one nothing can test. Its cost while unfiled: a walked-away
dialogue stays 'started' forever, so any count of dialogues in progress
over-counts without bound.

B120 gains a second symptom. A reader returning to a finished dialogue gets an
empty thread and a composer, because the console reads concluded off the newest
turn and a resumed dialogue has no turns. Their first reply is now answered 409
rather than 404, which is better and still a page offering an action it cannot
perform. The fix is B120's own -- a port that reads one dialogue whole -- plus
reading status from it rather than from the transcript."
```

---

### Task 5: The console tells a returning reader it finished

**Files:**
- Modify: `frontend/src/application/dialogue/dialogue-store.ts`
- Modify: `frontend/src/presentation/dialogue/DialoguePage.tsx`
- Modify: the corresponding `.test.ts`/`.test.tsx`
- Modify: `research_team/interfaces/web/static` (rebuilt)

**Scope, stated because it is narrow on purpose:** this task does **not** fix
B120. It does not add a read-one-dialogue port and does not restore a resumed
transcript. It makes the one thing Task 3 made possible visible: a 409 on reply
is rendered as "this dialogue has finished" rather than as a failure.

**Interfaces:**
- Consumes: `DialogueRepository.reply` rejecting with an `ApiError` of status 409.
- Produces: `DialogueState.concluded: boolean` — set from a 409 on reply, and
  read by `DialoguePage` **in addition to** the newest turn's flag.

- [ ] **Step 1: Write the failing tests**

Append to `dialogue-store.test.ts`:

```ts
it('treats a 409 on reply as the dialogue having finished, not as a failure', async () => {
  // Task 3 made this reachable: a reader who returns to a concluded dialogue
  // and types gets a 409. Rendered as an error, that reads as "something went
  // wrong"; rendered as concluded, it reads as what happened. Red against a
  // store whose catch writes every rejection to `error`.
  const dialogues = repo({
    reply: vi.fn().mockRejectedValue(new ApiError('dialogue has already concluded', 409)),
  })
  const store = createDialogueStore({ dialogues, projectId: PROJECT })
  await store.getState().start('t')

  await store.getState().send('one more?')

  expect(store.getState().concluded).toBe(true)
  expect(store.getState().error).toBeNull()
})

it('still reports a 404 as an error', async () => {
  // The other half, so the branch above cannot be implemented by swallowing
  // every rejection. A dialogue that genuinely is not there is a failure the
  // reader needs told.
  const dialogues = repo({
    reply: vi.fn().mockRejectedValue(new ApiError('no dialogue', 404)),
  })
  const store = createDialogueStore({ dialogues, projectId: PROJECT })
  await store.getState().start('t')

  await store.getState().send('hello?')

  expect(store.getState().concluded).toBe(false)
  expect(store.getState().error).toContain('no dialogue')
})
```

And to `DialoguePage.test.tsx`:

```tsx
it('shows the finished state from the store even with no turns to read it off', () => {
  // The page reads `concluded` off the newest turn, which is right during a
  // live dialogue and impossible on a resumed one -- a resumed dialogue has no
  // turns yet (B120). Red against a page that reads only the transcript: a
  // returning reader sees a composer for a dialogue that cannot take a reply.
  render(<DialoguePage {...props({ transcript: [], concluded: true })} />)

  expect(screen.getByText(/reached its goal/i)).toBeInTheDocument()
  expect(screen.queryByLabelText(/your answer/i)).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/application/dialogue src/presentation/dialogue`

Expected: FAIL — `concluded` is not on the store, and `DialoguePage` has no such
prop.

- [ ] **Step 3: Implement**

The store currently imports only `errorMessage` from `@application/ports/errors.ts`
— **add `ApiError` to that import**; without it this branch is a `ReferenceError`
at runtime and a type error at build, so it fails loudly rather than silently,
but it is the one line easy to miss when copying the branch below.

In the store's `send` catch, branch on the status **before** writing `error`:

```ts
      } catch (err) {
        // A 409 is not a failure: Task 3's route answers it when the dialogue
        // has concluded, which is a thing that happened rather than a thing
        // that went wrong. `instanceof ApiError` and an explicit status check,
        // never a substring match on the detail -- the wording is the server's
        // and is free to change.
        if (err instanceof ApiError && err.status === 409) {
          set({ concluded: true })
          return
        }
        ...
      }
```

In `DialoguePage`, take `concluded` as a prop and OR it with the transcript's:

```tsx
  // Either source. The transcript's flag is what a live dialogue has -- the
  // frame that concluded it is the newest turn's -- and the store's is what a
  // resumed one has, where there are no turns to read (B120). Neither covers
  // both cases, and a page that picked one shows a composer to a returning
  // reader whose dialogue has finished.
  const concluded = fromStore || (transcript[transcript.length - 1]?.concluded ?? false)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npx vitest run src/application/dialogue src/presentation/dialogue`

Expected: PASS.

- [ ] **Step 5: Wiring**

Run: `cd frontend && grep -n "concluded" src/presentation/dialogue/DialogueView.tsx`

Expected: the store slice is read and passed to `DialoguePage`. A store field
nothing reads is exactly the silo this plan's own wiring rule exists against.

- [ ] **Step 6: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

Then: `git status --porcelain research_team/interfaces/web/static`

Anything printed belongs in the commit — this is the only task in Plan 4 that
touches `frontend/src`, so drift here is yours.

- [ ] **Step 7: Commit**

```bash
git add frontend/src research_team/interfaces/web/static
git commit -m "Render a finished dialogue as finished when the reader comes back

A 409 on reply is not a failure. Task 3's route answers it when the dialogue
has concluded, which is a thing that happened rather than a thing that went
wrong, and rendering it in the error line tells a reader something broke when
their dialogue simply ended.

Branched on the status and never on the detail string: the wording is the
server's and is free to change. The 404 case has its own test so this cannot be
implemented by swallowing every rejection -- a dialogue that genuinely is not
there is still a failure the reader needs told.

The page now reads concluded from either the store or the newest turn, because
neither covers both cases. The transcript's flag is what a live dialogue has;
the store's is what a resumed one has, where there are no turns to read it off
at all (B120). A page that picked one shows a composer to a returning reader
whose dialogue has finished.

This does not fix B120. The transcript is still empty on a resumed dialogue and
that is still filed."
```

---
---

### Task 6: Let the reader end a dialogue

**Files:**
- Modify: `research_team/application/socratic.py` — `end`
- Modify: `research_team/interfaces/web/app.py` — the route
- Modify: `tests/integration/test_socratic_stream.py`
- Modify: `frontend/src/application/ports/repositories.ts`,
  `frontend/src/infrastructure/http/dialogue-repository.ts`,
  `frontend/src/application/dialogue/dialogue-store.ts`,
  `frontend/src/presentation/dialogue/DialoguePage.tsx`,
  `frontend/src/presentation/dialogue/DialogueView.tsx`, and their tests
- Modify: `research_team/interfaces/web/static` (rebuilt)

**Why this is a task and not a line in Task 2.** `"met"` is the model's verdict
about understanding and `"abandoned"` is the reader's decision to stop. They
share an event and share nothing else: different actor, different trigger,
different surface, and one must never be inferable from the other. Folding this
into Task 2 would put a reader-initiated command inside the judgement path,
where the only thing that can call it is a model.

**Scope:** ending, and the wording that goes with it. It does **not** add a read
route carrying *why* a dialogue ended — `_dialogue_view` has `status` and not the
reason — so a reader returning to a dialogue they ended is told it reached its
goal. Task 4 Step 3 files that.

**Interfaces:**
- Produces:

```python
# research_team/application/socratic.py
async def end(self, *, project_id: UUID, dialogue_id: UUID) -> None: ...
```

```ts
// frontend/src/application/ports/repositories.ts, on DialogueRepository
end(projectId: ProjectId, dialogueId: string): Promise<void>
```

  and on the store, `endedByReader: boolean` beside Task 5's `concluded`.

- [ ] **Step 1: Write the failing service and route tests**

Append to `tests/integration/test_socratic_stream.py`:

```python
async def test_a_reader_can_end_a_dialogue_and_the_reason_says_who_ended_it(client):
    """The other half of `ConclusionReason`, which nothing produced.

    Asserted on the stored event and not on the 200: `end` is one command, and a
    route that swallowed it would answer 200 with nothing written -- the exact
    shape CLAUDE.md's "Events" section describes, where an event no projection
    handles counts as APPLIED and silence is not refusal.

    `reason == "abandoned"` and not `"met"`, because a dialogue the reader
    stopped is not one the reader finished, and a stopping condition that could
    be satisfied by giving up would be worth nothing.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    ended = await http.post(f"/api/projects/{project_id}/dialogues/{dialogue_id}/end")

    assert ended.status_code == 200, ended.text
    events = await _events(application, UUID(dialogue_id))
    assert type(events[-1]) is SocraticDialogueConcluded
    assert events[-1].reason == "abandoned"


async def test_ending_a_dialogue_drops_its_live_entry(client):
    """**The line this task exists around.**

    `_resume` returns a cached `LiveDialogue` BEFORE it reads the row, so its
    concluded refusal cannot see a dialogue still in the registry -- the
    `cached is not None` early return sits above the `status == "concluded"`
    check. A reader who ends a dialogue and then types would be answered: the
    whole model call runs, and `decide` refuses only at save, as a
    `CommandRejectedError` that `reply_to_dialogue` does not catch. That reaches
    the browser as an in-band `error` frame on a 200 stream, after the tokens
    are spent.

    So `end` calls `forget`, and this test is what fails if that line is removed
    as redundant. Red against an `end` that writes the event and leaves the
    cache: the status below is 200, not 409.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]
    await http.post(f"/api/projects/{project_id}/dialogues/{dialogue_id}/end")
    await application.dialogues.caught_up()

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "more?"}
    )

    assert response.status_code == 409, response.text
    assert "concluded" in response.json()["detail"]


async def test_ending_a_dialogue_twice_is_refused_rather_than_written_twice(client):
    """`decide` refuses every command against a concluded dialogue, so a second
    `end` is a `CommandRejectedError`. Caught as 409 rather than left to become a
    500 -- a double-clicked button is not a server fault -- and asserted on the
    event count too, because a route that answered 409 while appending a second
    `SocraticDialogueConcluded` would look identical from the status alone.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]
    await http.post(f"/api/projects/{project_id}/dialogues/{dialogue_id}/end")

    again = await http.post(f"/api/projects/{project_id}/dialogues/{dialogue_id}/end")

    assert again.status_code == 409, again.text
    events = await _events(application, UUID(dialogue_id))
    assert [type(e) for e in events].count(SocraticDialogueConcluded) == 1


async def test_ending_a_dialogue_in_another_project_is_a_404(client):
    """The project check is the route's, not the command's:
    `ConcludeSocraticDialogue` carries no project id, so `decide` has nothing to
    compare -- the same gap `_resume`'s second refusal exists for. Without this
    check a guessed id ends someone else's dialogue and answers 200.
    """
    http, _application, _stub = client
    project_id = await _project(http)
    other = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    response = await http.post(f"/api/projects/{other}/dialogues/{dialogue_id}/end")

    assert response.status_code == 404, response.text
```

`_events` is the helper Task 2 writes in `test_a_dialogue_concludes.py`; repeat
its four lines here rather than importing across integration modules — a shared
helper is a dependency for four lines of `collect`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/integration/test_socratic_stream.py -x -k end`

Expected: FAIL — 404 from FastAPI, because the route does not exist.

- [ ] **Step 3: Add `end` to the service**

```python
    async def end(self, *, project_id: UUID, dialogue_id: UUID) -> None:
        """Stop a dialogue because the reader said so.

        `reason="abandoned"` is the stored value and is accurate about why it
        ended, but nothing the reader sees says it: a reader who wants to stop
        should be able to, and a conversation with no way to close it is a worse
        experience than the one this plan is fixing.

        **`forget` is not tidying.** `_resume` returns a cached `LiveDialogue`
        before it reads the row, so its concluded refusal cannot see a dialogue
        still in the registry. Without this line a reader who ends a dialogue and
        types is answered -- the model call runs in full and `decide` refuses
        only at save, as a `CommandRejectedError` the reply route does not catch,
        which reaches the browser as an in-band `error` frame on a 200 stream
        after the tokens are spent.
        `test_ending_a_dialogue_drops_its_live_entry` is 200 rather than 409 with
        it removed.

        `project_id` is taken and not used, exactly as `record_attempt` takes it:
        the route has already checked the row belongs to the project, and the
        argument is here so a later per-project scope is a change to this method
        rather than to every call site.
        """
        aggregate = await self._transcripts.load(dialogue_id)
        aggregate.execute(
            ConcludeSocraticDialogue(dialogue_id=dialogue_id, reason="abandoned")
        )
        await self._transcripts.save(aggregate)
        self.forget(dialogue_id)
```

`load`, never `load_or_create`: an id that names nothing must die at the
repository rather than open a stream and immediately conclude it. That is
`_record`'s rule and it holds here for the same reason.

- [ ] **Step 4: Add the route**

Beside `post_dialogue_attempt`, whose 404-then-409 shape this copies:

```python
    @app.post("/api/projects/{project_id}/dialogues/{dialogue_id}/end")
    async def end_dialogue(project_id: UUID, dialogue_id: UUID):
        """End a dialogue at the reader's request.

        POST and not DELETE: nothing is removed. The dialogue, its turns and
        every marked answer stay where they were and stay readable, which is the
        opposite of what the wrong verb would tell a reader.

        409 for one already concluded, matching `post_dialogue_attempt` and Task
        3's reply route, so the page has one rule for every "this dialogue has
        finished" it can meet.
        """
        if socratic is None or dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        try:
            await socratic.end(project_id=project_id, dialogue_id=dialogue_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "concluded"}
```

The row read is against the projection, so two ends inside one projection lag
both reach `socratic.end` — which is why the `CommandRejectedError` arm is what
makes a double-click safe, and not the row check.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/integration/test_socratic_stream.py -v`

Expected: PASS, including Task 3's two.

- [ ] **Step 6: Prove the `forget` load-bearing**

Delete `self.forget(dialogue_id)` from `end` and re-run
`test_ending_a_dialogue_drops_its_live_entry`. Expected: FAIL with 200, and the
stream body carries an `error` frame instead of a question — which is exactly
what the reader would have seen. Restore.

- [ ] **Step 7: The console button**

Port first: add `end` to `DialogueRepository` with a docstring saying a 409 means
already concluded and is not a failure. Then the repository method, in
`submitDialogueAttempt`'s shape:

```ts
  async end(projectId: ProjectId, dialogueId: string): Promise<void> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${seg(projectId)}/dialogues/${seg(dialogueId)}/end`,
      { method: 'POST' },
    )
    // No body parsed. The route answers `{"status": "concluded"}` and reading it
    // would change nothing -- a caller that got a 200 already knows what it says.
    if (!response.ok) throw new ApiError(await detail(response), response.status)
  }
```

Then the store action, beside `send`:

```ts
    end: async () => {
      const { dialogueId } = get()
      if (dialogueId === null) return
      try {
        await dialogues.end(projectId, dialogueId)
        set({ concluded: true, endedByReader: true })
      } catch (err) {
        // A 409 means it had already concluded: the reader's intent is satisfied
        // and there is nothing to report. Same rule as `send`'s 409 in Task 5 --
        // a state the reader wanted is not a failure.
        if (err instanceof ApiError && err.status === 409) {
          set({ concluded: true })
          return
        }
        set({ error: errorMessage(err) })
      }
    },
```

`endedByReader` is set only on the success path. The 409 branch sets `concluded`
alone, because a dialogue already concluded when this call landed was concluded
by something else — most likely the model, on the turn before.

Then `DialoguePage` takes `endedByReader` and `onEnd`, draws the button beside
the composer while the dialogue is live, and picks the wording:

```tsx
        <p className="dlg-concluded" role="status">
          {endedByReader ? 'You ended this dialogue.' : 'This dialogue has reached its goal.'}
        </p>
```

The default stays "reached its goal", and it is wrong for a reader who ended a
dialogue in an earlier session and came back: `endedByReader` is store state and
does not survive a refresh, because no read route carries the reason. Filed in
Task 4 Step 3 rather than papered over with vaguer wording — "This dialogue has
ended" would be true both ways and would stop telling the reader they got there,
which is the one line on this page that says the thing worked.

`DialogueView` passes `onEnd={() => void store.getState().end()}` and reads
`endedByReader` through the hook, beside the slices it already reads.

- [ ] **Step 8: The console tests**

To `dialogue-store.test.ts`:

```ts
it('marks the dialogue ended by the reader', async () => {
  const end = vi.fn().mockResolvedValue(undefined)
  const store = createDialogueStore({ dialogues: repo({ end }), projectId: PROJECT })
  await store.getState().start('t')

  await store.getState().end()

  expect(end).toHaveBeenCalledWith(PROJECT, store.getState().dialogueId)
  expect(store.getState().concluded).toBe(true)
  expect(store.getState().endedByReader).toBe(true)
})

it('does nothing when there is no dialogue to end', async () => {
  // Red against an action that calls the repository with a null id. The button
  // is drawn from the moment the page loads, and before `start` resolves there
  // is nothing to end -- the server would answer 404 and the reader would be
  // told their dialogue is missing when they have not begun one.
  const end = vi.fn()
  const store = createDialogueStore({ dialogues: repo({ end }), projectId: PROJECT })

  await store.getState().end()

  expect(end).not.toHaveBeenCalled()
  expect(store.getState().error).toBeNull()
})

it('treats a 409 on end as already concluded, and not as the reader ending it', async () => {
  const end = vi.fn().mockRejectedValue(new ApiError('already concluded', 409))
  const store = createDialogueStore({ dialogues: repo({ end }), projectId: PROJECT })
  await store.getState().start('t')

  await store.getState().end()

  expect(store.getState().concluded).toBe(true)
  // Not the reader's doing: something else concluded it first, most likely the
  // model on the previous turn, and telling the reader they ended it would be a
  // small lie about their own history.
  expect(store.getState().endedByReader).toBe(false)
  expect(store.getState().error).toBeNull()
})
```

To `DialoguePage.test.tsx`:

```tsx
it('offers a way to end a live dialogue and calls it', async () => {
  const onEnd = vi.fn()
  render(<DialoguePage {...props({ dialogueId: 'd1', onEnd })} />)

  await userEvent.click(screen.getByRole('button', { name: /end this dialogue/i }))

  expect(onEnd).toHaveBeenCalledTimes(1)
})

it('does not offer to end a dialogue that has already finished', () => {
  // Red against a button rendered unconditionally: it would sit under the
  // "reached its goal" line and 409 on every click.
  render(<DialoguePage {...props({ dialogueId: 'd1', concluded: true })} />)

  expect(screen.queryByRole('button', { name: /end this dialogue/i })).not.toBeInTheDocument()
})

it('says the reader ended it when the reader ended it', () => {
  render(<DialoguePage {...props({ dialogueId: 'd1', concluded: true, endedByReader: true })} />)

  expect(screen.getByText(/you ended this dialogue/i)).toBeInTheDocument()
  expect(screen.queryByText(/reached its goal/i)).not.toBeInTheDocument()
})
```

`props(...)` is the existing helper in that file; if it does not already take
`concluded`, that half arrives with Task 5 and this task adds `endedByReader` and
`onEnd` beside it.

Run: `cd frontend && npx vitest run src/application/dialogue src/presentation/dialogue src/infrastructure/http/dialogue-repository.test.ts`

Expected: PASS.

- [ ] **Step 9: Wiring**

| Link | Where | Confirm |
| --- | --- | --- |
| reader acts | `DialoguePage` button | `onEnd` prop, drawn only while live |
| passed | `DialogueView` | `onEnd={() => void store.getState().end()}` |
| store | `dialogue-store.ts` `end` | calls the repository |
| port | `DialogueRepository.end` | declared, so every fake must implement it |
| http | `dialogue-repository.ts` | POSTs `.../end` |
| route | `end_dialogue` | 404 / 409 / 200 |
| command | `ConcludeSocraticDialogue(reason="abandoned")` | executed on the loaded aggregate |
| stored | `SocraticDialogueConcluded.reason` | `"abandoned"` on the stream |

Run: `cd frontend && grep -rn "onEnd" src/presentation/dialogue src/application/dialogue`

Expected: the prop is *passed* by `DialogueView`, not merely accepted by
`DialoguePage`. A page that takes a handler nobody supplies compiles, renders a
button and does nothing — the silo the wiring rule exists against.

Run: `grep -rn "abandoned" research_team/`

Expected: `"abandoned"` now has a producer. If the only hits are the `Literal`
and the projection column, this task did not land.

- [ ] **Step 10: Gates and the committed build**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `cd frontend && npm run verify`
- `cd frontend && npm run build`, then
  `git status --porcelain research_team/interfaces/web/static`

Rebuild here even though Task 5 already did: `verify` runs a build and never
compares it against the committed tree, so a stale console passes green every
time and CI's "the committed build matches src/" is the only thing that says so.

- [ ] **Step 11: Commit**

```bash
git add research_team/application/socratic.py research_team/interfaces/web/app.py \
  tests/integration/test_socratic_stream.py frontend/src \
  research_team/interfaces/web/static
git commit -m "Let a reader end a dialogue they are done with

The other half of ConclusionReason, which nothing produced. A dialogue could end
because the reader demonstrated the thing; it could not end because the reader
decided to stop, and a conversation with no way to close it is a worse
experience than the one this plan is fixing.

The reader's action and not an idle sweep. The sweep needs a threshold over how
long a reader has been away -- the same arbitrary number this plan's design
section refused for deciding conclusion, applied to attention instead of
understanding -- and rejecting it there while accepting it here would be
incoherent. Filed instead.

reason='abandoned' is stored and never shown. It is accurate about why the
dialogue ended and it is not what a reader should read about themselves: the
button says end, and the page says you ended this dialogue.

end() calls forget(), and that line is the task. _resume returns a cached
LiveDialogue before it reads the row, so its concluded refusal cannot see a
dialogue still in the registry: without the drop, a reader who ends a dialogue
and types is answered in full, and decide refuses only at save as a
CommandRejectedError the reply route does not catch -- an in-band error frame on
a 200 stream, after the tokens are spent. Proved by removing it.

The store separates concluded from endedByReader. A 409 sets only the first: a
dialogue already concluded when the call landed was concluded by something else,
most likely the model on the turn before, and telling the reader they ended it
would be a small lie about their own history.

What this does not do: no read route carries the reason, so endedByReader does
not survive a refresh and a returning reader is told their ended dialogue
reached its goal. Filed rather than papered over with wording vague enough to be
true both ways -- that would cost the one line on this page that tells a reader
they got there."
```

---

## Self-review

**Spec coverage.**

| Spec | Where |
| --- | --- |
| the headline — stops when the reader demonstrated it, not when they stop typing | Tasks 1 and 2 |
| §5 `SocraticDialogueConcluded(reason)` written by something | Task 2 |
| §5 `SocraticProgressObserved` from the model's assessment | Tasks 1 and 2 |
| §5 the stopping condition is not the model's to move | Task 1's prompt says so; the aggregate holds it |
| §3 attempts as evidence, kept distinct from opinion | already built; Task 1 preserves `evidence="assessment"` |
| §9 the parse refuses rather than defaults, testable without a model | Task 1, with a prove-it-red step |
| §9 four gates plus the fifth | every task; Task 5 owns the rebuilt assets |
| §5 `reason="abandoned"` | Task 6 — the reader ends it; the idle sweep is filed in Task 4 |

**What I could not plan cleanly:**

1. **A reader who ends a dialogue is told, on their next visit, that it reached
   its goal.** Task 6 stores `reason="abandoned"` and no read route carries it —
   `_dialogue_view` has `status` and not the reason — so `endedByReader` is store
   state that does not survive a refresh. The honest alternatives were both
   worse: a vaguer line ("This dialogue has ended") is true either way and gives
   up the one sentence on the page that tells a reader they got there, and adding
   the reason to the read path is B120's shape of work in a task that is already
   the widest here. Filed in Task 4 Step 3.
2. **Task 5 is a partial fix on top of a filed gap.** It renders the finished
   state for a returning reader without fixing B120, so a resumed concluded
   dialogue shows "this dialogue has reached its goal" above an empty thread.
   That is better than a composer that 409s and worse than showing the
   conversation. Doing it properly means a read-one-dialogue port, which is
   B120's whole content and a different plan's worth of work.
3. **Plan 2's and Plan 3's tests that drive the real executor with a fake model
   will need their fixtures updated**, because the model's reply must now parse
   as a judgement. Task 2 Step 5 names this and says a failure there is a real
   consequence rather than a broken test — but I could not enumerate which tests
   in advance without running them, so the step is a check rather than a list.

**Inline decisions:**

- **Judge every turn (Option A), not a gate over evidence (Option B).** The
  deciding argument is that B's threshold would be a second stopping condition,
  unwritten and untestable, in front of the one the author wrote — a hidden
  numeric gate undoing the argument the aggregate exists to make. Contamination
  handled by ordering (`concluded` first in the block) and by allowing an empty
  prompt when concluding, which also keeps `SOCRATIC_METHOD_PROMPT` from being
  contradicted by the format it is asked to answer in.
- **`"abandoned"` is the reader's action and nothing sweeps.** An idle sweep
  needs the same arbitrary threshold Option B was refused for, applied to
  attention instead of understanding; accepting it here after rejecting it there
  would be incoherent. Leaving the branch unreachable was the other option and it
  is the worst of both — this plan exists to remove exactly that shape.
- **Ending, never abandoning, in anything the reader reads.** `reason="abandoned"`
  is the stored value because it is accurate about why the dialogue ended; the
  button says end and the page says "You ended this dialogue."
- **`end` calls `forget`.** `_resume`'s cache hit precedes its concluded check,
  so without the drop a reader who ends a dialogue and types pays for a full
  model call and gets an in-band `error` frame on a 200 stream. Proved by
  deleting the line.
- **The store keeps `endedByReader` separate from `concluded`.** A 409 sets only
  the second: something else concluded it, most likely the model on the previous
  turn.
- **`_framing_fields` generalised to `_declared_fields(prompt)`** rather than
  copied, so the judgement block gets the identical derive-from-the-prompt guard.
- **`concluded` must be a real `bool`.** YAML returns `"maybe"` as a truthy
  string, and `bool(loaded.get(...))` would end dialogues on it.
- **`observation` is the one optional key**; manufacturing an empty one would
  write a `SocraticProgressObserved` per turn and bury the real ones.
- **`prompt` comes from the parse, never `last_text(final)`** — the fallback
  would show the reader the raw YAML block as the dialogue's closing words.
- **`DialogueConcluded` subclasses `UnknownDialogue`**, so no existing caller
  changes silently; the cost is that the route's `except` order becomes
  load-bearing, proved by swapping it.
- **409, not 410**, matching what `post_dialogue_attempt` already answers, so the
  page has one rule for both.
- **The store branches on `err.status === 409`, never on the detail string** —
  the wording is the server's and free to change.
- **`_record` is not edited by any task.** The write path was complete before
  this plan started; a diff there means something went wrong.

**Placeholder scan.** No "TBD", no "add error handling", no "write tests for the
above", no "similar to Task N". Task 4 is prose-only by nature — it is a
`BACKLOG.md` edit — and its steps say what each entry must contain rather than
quoting a finished entry, which is the one place this plan gives shape instead of
text. Task 3 Step 1 notes the `client` fixture may need a settable `prompts` and
says to adjust it rather than assuming; that is a check, not a gap.

**Type consistency.** `SocraticJudgement`, `parse_judgement`, `_JUDGEMENT_FIELDS`,
`_declared_fields`, `SOCRATIC_JUDGEMENT_PROMPT` are spelled identically in Tasks 1
and 2. `SocraticPrompt`, `SocraticObservation`, `EvidenceKind`,
`ConcludeSocraticDialogue`, `SocraticDialogueConcluded`, `UnknownDialogue` are as
they landed — read from `socratic_dialogue.py` and `socratic.py` at `c805ecd`,
not from Plans 1–3's text. `DialogueConcluded` is new in Task 3 and used in Tasks
3 and 5. `end` is spelled the same on the service, the port, the repository and
the store; `endedByReader` and `onEnd` are the same names in the store, the view,
the page and both test files. The console's `concluded` prop is the same name in the store, the page
and both tests.
