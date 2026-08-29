"""Taking the corpus away from a parent that has stopped writing with it.

**This exists because of a spiral, and the spiral is in the log.** Session
`8519cab4` -- the `mid-2000s` area of the owner's Star Trek project, run three
times on 2026-08-29 with byte-identical results -- spent 18 model calls and 30
tool calls in course authoring's phase 1, of which twelve consecutive
`graph_describe` calls carried rephrasings of one question (`mid-2000s Star
Trek era after Enterprise ended`, `mid-2000s period in Star Trek history`, `the
mid-2000s event in Star Trek`, ..., `mid-2000s`), each returning about 900
characters of the same thin material. It then called `ls` on its own output
directory, received `No files found`, and returned `content: ""` with no tool
calls and `finish_reason: "stop"`. It never called `write_file`.
`check_stage_one` refused the run at `unit.md was not written`, and four phases
of work were thrown away.

**It is not a context-window overflow, and that was the first guess.** Measured
over all 22 course-authoring sessions in the owner's database, replaying
`ElideToolResults` as `.env` configures it: the largest request any authoring
turn has ever built is ~42k tokens against a 64k-context model, and this
particular run peaked at **7,275**. The window was never the constraint. What
is unbounded is the number of tool rounds inside one phase, and a phase that
spends its rounds researching arrives at the write with nothing left to say.

**The threshold was derived from the log, and the log gave the wrong number.**
This is worth reading before changing it, because the reasoning was sound and
the answer was inert.

The first `DEFAULT_ROUNDS` was 16, from phase 1's *total* model calls per
session: 10, 8, 12 and 15 in the four that completed all four phases; 18
(three times, the run above), 41 and 12 in ones that died. Above every
success, below every spiral -- and **measured to change nothing.** Replaying
the stored 4,891-character phase-1 prompt against the live endpoint on
2026-08-29, budget off and budget at 16 gave byte-identical outcomes:
`rounds=18 tool_results=30 unit.md written=False reply_chars=0`, refused at
`unit.md was not written` both times. By round 17 the model had already
stopped researching -- round 17 was `ls`, round 18 was the empty stop -- so a
bound that bites at 17 bites after the failure is over.

The quantity that matters is not how many rounds a phase takes but **how many
it takes before it first writes anything**, and those are different numbers
because the budget withdraws only the reading tools: a phase cut off at round
6 keeps writing at rounds 7 through 20. Measured across all 22 sessions, the
round of the first `write_file`/`edit_file`/`task` call: 6, 2, 2, 1 / 5, 8, 2,
1 / 6, 1, 2, 1 / 9, 6, 2, 1 in the four that finished, and NEVER (18 rounds)
three times in the run above.

Three live runs of the same prompt against the same model and project settle
it:

| `AGENT_AUTHORING_ROUNDS` | rounds | tool results | `unit.md` | checkpoint |
|---|---|---|---|---|
| 0 (off) | 18 | 30 | no | refused |
| 16 | 18 | 30 | no | refused |
| 10 | 68 | 83 | **yes** | pass |
| 6 | 20 | 24 | **yes** | pass |

`DEFAULT_ROUNDS` is 6: it is the only measured value that both passes and
stays cheap. 10 also passes, and costs 3.4x the rounds and 3.5x the tool calls
to do it -- far outside the ~10% band this project treats as single-run noise,
so the gap is real even from one run each.

**What 6 costs, stated plainly.** Of the phase 1s on record that did write,
several first wrote at rounds 7, 9, 10 and 11, so this cuts their reading
short. That is not the same as stopping them -- they keep every writing tool
and every subagent, and the one case where it was actually measured
(`mid-2000s` at 6) went from refused to passing. But it is a real narrowing,
it was chosen on one corpus against one model, and `AGENT_AUTHORING_ROUNDS`
exists so that whoever meets a corpus it is wrong about does not have to edit
code.

**What it does is withdraw tools, not add prose.** A system-prompt sentence
asking the model to stop researching is exactly the shape CLAUDE.md's
"Checkpoints over model output" section is about: an instruction the model may
decline, invisible when it does. Removing the tools from the request is
enforcement -- past the budget the model holds the file and dispatch tools and
nothing to read with, so the only move left is the one the phase is for. The
sentence is added *too*, because a model whose tools vanished with no
explanation reports that it is unable to continue rather than writing.

What this deliberately does not do is bound a *subagent*. The middleware is
installed on the parent graph only, and `lesson-drafter` and the rest run their
own agents with their own full tool sets. That is the intended asymmetry, and
it is the whole shape the fix is arguing for: the parent plans and dispatches,
the reading happens in the fan-out where its cost is paid per unit and comes
back as a conclusion rather than as a transcript.
"""

from collections.abc import Awaitable, Callable, Collection
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from research_team.infrastructure.config import DEFAULT_AUTHORING_ROUNDS

#: Model calls a parent authoring turn may make before its reading tools go.
#:
#: An alias, not a second definition: the value lives in `config` because that
#: module imports nothing from the project, and the paragraph above is what it
#: means. See the module docstring for the three live runs that fixed it at 6,
#: and for why the number derived from the log alone was 16 and inert.
DEFAULT_ROUNDS = DEFAULT_AUTHORING_ROUNDS

#: The tools withdrawn once the budget is spent, by name.
#:
#: Everything that *reads* -- the graph, the corpus, the web. Not the file
#: tools, not `task`, not `ls`: a parent at its budget still has to write the
#: file and dispatch the subagents, and taking those would turn a bounded run
#: into a stopped one. Named rather than derived from a `read_only` flag,
#: because no such flag exists and inventing one to spare seven literals would
#: put the decision two modules away from the measurement that produced it.
RESEARCH_TOOLS: frozenset[str] = frozenset(
    {
        "graph_search",
        "graph_describe",
        "list_sources",
        "read_source",
        "search_sources",
        "web_search",
        "fetch",
    }
)

BUDGET_NOTICE = (
    "\n\nYou have used this turn's research budget: the graph, corpus and web "
    "tools are no longer available to you for the rest of this turn. This is "
    "not an error, and re-reading is not an option you have. Write the files "
    "this phase asks for now, from what you already have, and dispatch the "
    "subagents it names -- they can still read. If a detail is missing, write "
    "the file without it rather than writing nothing: a unit with a thin "
    "section is work, and a turn that ends with no file is discarded whole."
)


class ResearchBudget(AgentMiddleware):
    """Withdraws a parent authoring turn's reading tools past `rounds` calls.

    One instance per turn. The count lives on the instance rather than in a
    context variable -- unlike `SearchAttempts`, which is shared across turns
    and needs `SearchAttemptsMiddleware` to reset it -- because
    `composition.turn_middleware` builds this fresh on every pass, so the reset
    is by construction and there is nothing to forget. The cost of that choice
    is that two concurrent turns get two budgets, which is the behaviour we
    want and the reason the shared-instance shape was not copied.
    """

    def __init__(
        self,
        *,
        rounds: int = DEFAULT_ROUNDS,
        research_tools: Collection[str] = RESEARCH_TOOLS,
        notice: str = BUDGET_NOTICE,
    ) -> None:
        super().__init__()
        self._rounds = rounds
        self._research = frozenset(research_tools)
        self._notice = notice
        self._calls = 0

    @property
    def name(self) -> str:
        """Explicit for `SearchAttemptsMiddleware`'s reason: langchain's
        factory raises when two middleware share a name, and the default is the
        class name."""
        return "research_budget"

    @property
    def calls(self) -> int:
        """Model calls this turn has made. Read by tests, not by the graph."""
        return self._calls

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Count this call, and strip the reading tools once the budget is out.

        Counted *before* the handler rather than after, so the call that spends
        the last of the budget still has its tools and the one after it does
        not. Counting afterwards grants `rounds + 1` reading calls, which is
        one more spiral round than the measurement justifies;
        `test_the_budget_covers_exactly_the_rounds_it_names` pins the boundary
        in both directions, because an off-by-one here is invisible in any test
        that only checks that the budget eventually bites.
        """
        self._calls += 1
        if self._calls <= self._rounds:
            return await handler(request)
        kept = [tool for tool in request.tools if _tool_name(tool) not in self._research]
        # `system_prompt` as well as `tools`. That half is reasoned rather than
        # measured: a model whose tools disappear with no explanation has been
        # seen to report that it cannot continue, and it is the half a live run
        # would revise first.
        return await handler(
            request.override(tools=kept, system_prompt=request.system_prompt + self._notice)
        )


def _tool_name(tool: Any) -> str:
    """A tool's name, whether it arrives as a `BaseTool` or as a rendered dict.

    Both shapes reach `ModelRequest.tools`: langchain passes an
    already-structured tool definition through unconverted. A version that
    assumed `.name` would keep every dict-shaped research tool, which is a
    budget that does nothing and reads from the outside exactly like one that
    works -- the silent-no-op shape CLAUDE.md's Events section is about.
    """
    if isinstance(tool, dict):
        return str(tool.get("name") or (tool.get("function") or {}).get("name") or "")
    return str(getattr(tool, "name", "") or "")
