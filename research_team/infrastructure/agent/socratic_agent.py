"""A deep agent that leads a reader by questioning, and changes nothing.

The prompts behind `SocraticDialogueService`, and `DeepAgentSocraticExecutor`,
which reuses the ask executor's plumbing wholesale -- the same read-only tool
set, the same file backend, the same activity translation -- differing in
exactly one thing that matters: what the model is told to do with them.

**The prompt is composed from pieces and never appended to `ASK_PROMPT`.**
`ask_agent.py:147` rebinds `ASK_PROMPT` to include its component reference,
which covers nine types -- measured on 2026-08-17, `component_reference` for
those nine is 9,600 characters. Appending would inherit six resolved types
silently, and it would *work*, which is why nothing but
`test_the_reply_prompt_is_built_from_the_pieces_and_not_from_the_ask_s` would
catch it. What it would cost is the surface: a model handed six ways to answer
with a drawing, on a page whose whole method is asking, writes a slideshow.

**Two assembled prompts, because there are two calls.** `frame` runs once and
turns a topic into a goal, a stopping condition and an opening question;
`respond` runs per exchange and is handed that framing. One prompt for both
would invite the model to re-decide the goal every turn, and a goal the model
can revise is not a stopping condition anything can test.

The cost of a prompt is paid per turn, so the sizes are worth recording rather
than guessing at. Re-measured on 2026-08-18, after the judgement block was
folded in (1,141 characters of it): the reply prompt is 7,724 characters and
the framing prompt 2,703 -- against the ask's 13,255. Almost the whole gap
between the two is the component reference the framing call deliberately does
without (2,482 characters for two types, where the ask's nine cost 9,600).
"""

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import yaml
from deepagents import FilesystemMiddleware, create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from research_team.application.components import component_reference
from research_team.application.corpus_read import REFERENCE_SYNTAX_PROMPT
from research_team.application.ports import ActivityReporter
from research_team.application.socratic import (
    DialogueMessage,
    SocraticFraming,
    SocraticObservation,
    SocraticPrompt,
)
from research_team.application.socratic_components import SOCRATIC_COMPONENT_TYPES
from research_team.infrastructure.agent.ask_agent import (
    READ_ONLY_FILE_TOOLS,
    citations,
    readable,
)
from research_team.infrastructure.agent.deep_agent import (
    to_activity_delta,
    to_activity_message,
)
from research_team.infrastructure.agent.messages import last_text
from research_team.infrastructure.agent.read_only_backend import ReadOnlyProjectBackend

SOCRATIC_TOOLS_PROMPT = (
    """You can read one research project's gathered material and change none of it.

You have its sources, its knowledge graph, its topics and its files. You have no
access to the web. The sources are mounted read-only at `/sources/<source_id>`,
so `grep` searches all of them at once; `ls` and `glob` are how you find out
what is there before searching it. Open one with `read_source`, not `read_file`:
only `read_source` returns the `source_id@start-end` span that makes a quote
checkable.

If the material does not cover something, say so plainly rather than filling the
gap from memory. A dialogue that invents its ground is worse than one that stops.

"""
    + REFERENCE_SYNTAX_PROMPT
)
"""The half both calls share. Deliberately the same claims the ask agent makes
about the same tools -- the tool set is identical and a second, drifting
description of it would be a second thing to keep true.

It had already drifted, and this was measured rather than feared: `ls` and
`glob` are in `READ_ONLY_FILE_TOOLS`, which
`DeepAgentSocraticExecutor` hands the agent, and neither was mentioned here
until 2026-08-18 --
`test_the_tools_prompt_describes_every_file_tool_the_executor_actually_admits`
was red on both when first run. That test covers the *file* tools only; the
project tools that survive `readable(project_tools)` need a built project to
enumerate and are still described by nothing that would notice a change."""

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

Do not answer the question for them. If they ask you directly, that is still not
a reason to -- say what you would need them to work out first, and ask about
that.
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

SOCRATIC_COMPONENT_PROMPT = """
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

""" + component_reference(only=SOCRATIC_COMPONENT_TYPES)

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
"""The judgement half of the reply turn. `concluded` is shown first because the
model answers in the order it is shown, and a verdict written after the question
is one chosen to justify asking it -- structural mitigation rather than a plea
in prose. `_declared_fields` reads the keys off this block, so the order and the
key names here are both load-bearing."""

SOCRATIC_PROMPT = (
    SOCRATIC_TOOLS_PROMPT
    + SOCRATIC_METHOD_PROMPT
    + SOCRATIC_COMPONENT_PROMPT
    + SOCRATIC_JUDGEMENT_PROMPT
)
"""The reply turn. Composed -- see the module docstring for why not appended."""

SOCRATIC_FRAMING_SYSTEM = SOCRATIC_TOOLS_PROMPT + SOCRATIC_FRAMING_PROMPT
"""The framing turn. No component reference: this call returns three strings,
not an utterance to the reader, and offering it widget syntax invites a goal
with an `mcq` in it."""


_YAML_LOADER: type = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
"""The fastest *safe* loader this PyYAML has, declared here rather than
imported from `components.py` -- that one is a private name in the application
layer, and infrastructure reaching across for it would be a dependency
`tests/test_architecture.py` does not forbid and nobody wants. `CSafeLoader`
and not `CLoader`: this parses a language model's output, which is exactly the
input that must not be able to construct Python objects."""

_FENCE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)


def _declared_fields(prompt: str) -> tuple[str, ...]:
    """The keys a prompt's own fenced block asks the model for, read off the
    prompt itself.

    Was `_framing_fields`, taking no argument and closing over
    `SOCRATIC_FRAMING_PROMPT`. Generalised to a parameter when the judgement
    block needed the identical guard: a second copy would be a second place for
    a derivation to stop matching the prompt it derives from, which is precisely
    the failure the derivation exists to prevent.

    **Derived rather than written alongside, and that is the whole reason this
    function exists.** The prompt shows a three-key YAML block and the parser
    below refuses anything missing one of them; written as two independent
    literals, a rename on either side produces a parser that refuses every
    well-formed framing, or a key nothing ever reads. Neither failure has a
    symptom a caller could act on -- the first fails every `begin` with a
    message naming a key the model did send, the second fails none.

    Returns nothing rather than guessing if the prompt's fenced block ever
    stops being a YAML mapping. `parse_framing` would then demand no fields at
    all, so both callers'
    `test_the_parser_asks_for_exactly_the_keys_the_..._prompt_asks_for` is what
    fails -- loudly, in a unit test -- instead of a dialogue quietly framing
    itself with empty strings.
    """
    fenced = _FENCE.search(prompt)
    if fenced is None:
        return ()
    block = yaml.load(fenced.group(1), Loader=_YAML_LOADER)
    return tuple(block) if isinstance(block, dict) else ()


_FRAMING_FIELDS = _declared_fields(SOCRATIC_FRAMING_PROMPT)
_JUDGEMENT_FIELDS = _declared_fields(SOCRATIC_JUDGEMENT_PROMPT)
"""What the judgement block declares. Read by
`test_the_parser_asks_for_exactly_the_keys_the_judgement_prompt_asks_for` and by
nothing in the parser itself -- `parse_judgement` cannot loop over these the way
`parse_framing` does, because the three keys have three different rules
(`concluded` a real bool, `prompt` conditional, `observation` optional). The
derivation still earns its place: it is what fails when a key is renamed in the
prompt and not here."""


def parse_framing(text: str) -> SocraticFraming:
    """The three strings a framing call must produce, or a refusal.

    **Refused rather than defaulted, and that is the whole of this function.**
    A `.get(key, "")` implementation is one line shorter and produces a
    dialogue framed with an empty stopping condition -- one that can never
    stop, and that looks entirely normal to a reader until they give up. Here
    the failure lands at `begin`, where the reader has spent one click.

    Module-level rather than a method on the executor so that the refusal is
    reachable without a model call: a private method would put every one of
    these cases behind a fake chat model.

    The fence is optional because models include it roughly half the time, and
    a framing that failed for want of three backticks would fail the whole
    dialogue at its first call.
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
    try:
        return SocraticFraming(
            goal=str(loaded["goal"]).strip(),
            stopping_condition=str(loaded["stopping_condition"]).strip(),
            opening_prompt=str(loaded["opening_prompt"]).strip(),
        )
    except KeyError as error:
        # Only reachable when `_FRAMING_FIELDS` did not demand the key that is
        # absent -- that is, when `_declared_fields` failed open and returned
        # `()` because the prompt's fenced block stopped being a YAML mapping.
        # Failing open is deliberate (see `_declared_fields`); failing open with
        # the *wrong exception type* is not, because `begin`'s callers and every
        # test here expect `ValueError`, and a `KeyError` would escape a
        # `pytest.raises(ValueError)` and every `except ValueError` upstream.
        raise ValueError(
            f"the framing is missing {error.args[0]}, and the prompt no longer "
            "declares it either -- see `_declared_fields`"
        ) from error


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
    `SocraticProgressObserved` per turn and bury the real ones. It is recorded
    as `evidence="assessment"` and never `"attempt"` -- it is the model's
    reading of the reader, not a marked answer, and a stopping condition met
    entirely by assessments is a dialogue that graded its own homework.

    The fence is optional for `parse_framing`'s reason: models include it
    roughly half the time.

    `test_a_judgement_that_cannot_be_read_is_refused_rather_than_defaulted`
    fails on every branch below except the no-question one, which is
    `test_a_turn_that_concludes_nothing_and_asks_nothing_is_refused`. The error
    strings are matched on: every refusal says "judgement" except that one,
    which says "question", so a rewording that collapsed them would make one of
    those tests pass for the wrong reason.
    """
    fenced = _FENCE.search(text)
    body = fenced.group(1) if fenced else text
    try:
        loaded = yaml.load(body, Loader=_YAML_LOADER)
    except yaml.YAMLError as error:
        raise ValueError(f"the judgement did not parse as YAML: {error}") from error
    if not isinstance(loaded, dict):
        raise ValueError(f"the judgement was not a mapping, got {type(loaded).__name__}")
    concluded = loaded.get("concluded")
    if not isinstance(concluded, bool):
        raise ValueError(
            f"the judgement's `concluded` was not true or false, got {concluded!r}"
        )
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

    **The tool set is the ask's, deliberately.** `READ_ONLY_TOOLS`,
    `READ_ONLY_FILE_TOOLS` and `CITED_BY_TOOL` are module constants in
    `ask_agent.py` with no injection point, and the design puts changing the
    allowlist out of scope for the first release. Reused rather than
    re-declared: a second copy of the allowlist is a second thing to keep in
    step, and nothing would fail if they drifted -- the dialogue would simply
    stop being able to open a source.

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
        # `last_text` rather than the tail message: the final state can end on a
        # `ToolMessage`, and the framing call is allowed to read the corpus.
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

        The stream loop is `DeepAgentAskExecutor.run`'s, structurally
        unchanged. A second streaming shape would be a second place the
        `values`/`messages` interleaving has to be got right, and that
        interleaving is the part that decides whether a reader sees anything at
        all while waiting.
        """
        agent = await self._agent(project_id, self._system_prompt)
        messages = _framed_history(history, goal, stopping_condition, reply)
        final: list[BaseMessage] = list(messages)
        reported = len(messages)
        async for mode, chunk in agent.astream(
            {"messages": messages}, stream_mode=["values", "messages"]
        ):
            if mode == "values":
                final = chunk.get("messages", final)
                for message in final[reported:]:
                    note = to_activity_message(message)
                    if note is not None:
                        on_activity(note)
                reported = len(final)
            elif mode == "messages":
                delta = to_activity_delta(chunk)
                if delta is not None:
                    on_activity(delta)

        return SocraticPrompt(
            prompt=last_text(final),
            citations=citations(final),
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
