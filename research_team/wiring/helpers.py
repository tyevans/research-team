"""Wiring helpers for context strategies, subagent rosters, and model selection."""

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel

from research_team.infrastructure import config
from research_team.infrastructure.agent import build_extraction_model
from research_team.infrastructure.agent.authoring_subagents import AUTHORING_SUBAGENTS
from research_team.infrastructure.agent.compaction import SummarizingStrategy
from research_team.infrastructure.agent.delegation import (
    DEFAULT_SUBAGENTS,
    DELEGATION_PROMPT,
)
from research_team.session.application.context import (
    ContextStrategy,
    ElideToolResults,
    FullHistory,
)
from research_team.session.domain import (
    Session,
    SessionPurpose,
)


def _context_parts(
    mode: str, model: BaseChatModel, system_prompt: str
) -> tuple[ContextStrategy, tuple[dict, ...], str]:
    """Turn a mode name into a strategy, subagents, and a prompt suffix.

    The three modes treat the same problem differently: `elide` shortens what
    is replayed, `compact` replaces it with a summary, and `delegate` keeps it
    from accumulating by sending work to a fresh context. Only this function
    knows the mapping; everything else takes what it is given.
    """
    if mode == "elide":
        return (
            ElideToolResults(
                keep_results=config.context_keep_results(),
                clear_over_chars=config.context_clear_over_chars(),
            ),
            (),
            "",
        )
    if mode == "compact":
        return (
            SummarizingStrategy(
                model,
                trigger_tokens=config.context_trigger_tokens(),
                keep_messages=config.context_keep_messages(),
            ),
            (),
            "",
        )
    if mode == "delegate":
        # Delegation does not transform the history -- there is simply less of
        # it, because the expensive work happened somewhere else.
        return FullHistory(), DEFAULT_SUBAGENTS, DELEGATION_PROMPT
    return FullHistory(), (), ""


def _subagents_for(session: Session, default: Sequence[dict]) -> Sequence[dict]:
    """The roster this turn may dispatch.

    Authoring is the only purpose with its own roster, and the check is on
    purpose rather than on the presence of a course directory: a session's
    purpose is fixed when it starts, where a directory appears partway through
    the first phase, which would give phase 1 a different roster from phase 2.

    **`default` is empty under the configuration this project actually runs.**
    Only the `delegate` branch of `_context_parts` returns a non-empty tuple,
    and `.env` sets `AGENT_CONTEXT=elide`, so the mode supplies no baseline
    roster and this function is the only thing that will ever put a subagent in
    an authoring turn. A reader who assumes the six are being *added* to
    something is wrong; on the real configuration they are the whole list.
    `test_a_chat_session_gets_the_modes_own_roster_and_no_authoring_one` is
    parametrised over all three modes for that reason -- against `elide` alone
    its assertion is `() == ()`, which the `delegate` case is there to redeem.

    The seventh subagent is deliberate and could not be removed anyway.
    deepagents inserts a `general-purpose` spec of its own unless the roster
    already holds one; the `general_purpose_subagent=...` escape the library's
    own docstring advertises (`graph.py:404`) is a *harness profile* field
    derived from the model, and `create_deep_agent` in 0.7.6 takes no such
    argument -- measured against the installed package on 2026-08-24, not read.
    So an authoring turn gets seven, and the only way to have six would be to
    ship a `general-purpose` spec of our own, which is still seven. What it
    costs: the authoring prompts name six subagents and say when to use each,
    and a parent that finds a nameless seventh may route work around the roster
    -- past `prose-critic` and `unit-reviewer`, which exist because the plan is
    expected to leak. `test_general_purpose_cannot_be_disabled_through_
    create_deep_agent` fails on a version that adds the argument, which is when
    to re-take this decision rather than inherit it.
    """
    if session.state.purpose is SessionPurpose.COURSE_AUTHORING:
        return AUTHORING_SUBAGENTS
    return default


def _extraction_model(injected: BaseChatModel | None) -> BaseChatModel:
    """The chat model knowledge extraction runs on, given what the caller passed.

    An injected model is handed back untouched. `build_application(model=...)`
    is how tests supply fakes, and a fake is not a `ChatOpenAI` -- it has no
    `extra_body` to set, and rebuilding one here would quietly point extraction
    at a real endpoint the test never asked for. Wrapping the injected model in
    a copy carrying `extra_body` would be no better: nothing guarantees the
    fake can be copied, and a caller who injects a model has said which model
    they want used.

    A model this project built for itself is a `ChatOpenAI` against
    `config.base_url()`, so extraction gets its own with thinking turned off --
    see `build_extraction_model`. The agent's model is deliberately left
    alone; only extraction is measured to be better off not reasoning.
    """
    return injected if injected is not None else build_extraction_model()
