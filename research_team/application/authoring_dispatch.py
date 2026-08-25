"""The names of the authoring subagents, and how the parent is told about them.

This is the seam between a phase prompt and the roster it dispatches, and it
lives in `application/` for one mechanical reason: `course_authoring.py` needs
the dispatch paragraph, `tests/test_architecture.py` forbids `application`
importing `infrastructure`, and the paragraph is prompt text with no runtime
dependency to justify the exception. The specs themselves stay in
`infrastructure/agent/authoring_subagents.py`, where they are handed to
deepagents; only the names and the prose move here, and infrastructure
importing this points inward.

**The names are constants because the drift is silent.** A parent told to
dispatch a subagent that does not exist does not fail -- it simply never calls
it, and the run settles with one phase's work quietly missing. The reverse, a
spec no prompt mentions, is dead weight nobody notices either. Both directions
are asserted in `tests/infrastructure/test_authoring_subagents.py`; neither
would be caught by anything else, because the failure has no exception in it.
"""

UNIT_CRITIC_NAME = "unit-critic"
ANECDOTE_HUNTER_NAME = "anecdote-hunter"
LESSON_DRAFTER_NAME = "lesson-drafter"
PROSE_CRITIC_NAME = "prose-critic"
QUIZ_WRITER_NAME = "quiz-writer"
UNIT_REVIEWER_NAME = "unit-reviewer"

#: Every name, in dispatch order. The order is the phases' order and is what
#: makes the roster paragraph below readable as a sequence rather than a menu.
AUTHORING_SUBAGENT_NAMES = (
    UNIT_CRITIC_NAME,
    ANECDOTE_HUNTER_NAME,
    LESSON_DRAFTER_NAME,
    PROSE_CRITIC_NAME,
    QUIZ_WRITER_NAME,
    UNIT_REVIEWER_NAME,
)

AUTHORING_DISPATCH_PROMPT = (
    "\n\nYou can hand scoped authoring work to six subagents with the `task` "
    "tool. Each starts with none of this conversation and returns only its "
    "conclusion, so brief it as you would someone who has read nothing: state "
    "the objective, name every file by path, and paste anything it needs that "
    "is not on disk.\n\n"
    "In roughly this order:\n"
    f"- `{UNIT_CRITIC_NAME}`, once, after `unit.md` exists and before you fix "
    "the plan. It judges each enduring understanding as arguable, central and "
    "corpus-supported. Revise `unit.md` yourself from what it returns.\n"
    f"- `{ANECDOTE_HUNTER_NAME}`, once, before drafting, so the plan can "
    "assign each find to a lesson. It may return nothing, and nothing is an "
    "acceptable answer -- do not send it back to look harder.\n"
    f"- `{LESSON_DRAFTER_NAME}`, one per lesson, in parallel. Only after the "
    "plan fixes every shared decision: the claim each lesson owns, its opening "
    "move, what it may assume from earlier lessons, and which anecdotes are "
    "its own. Whatever you leave open, each drafter answers differently.\n"
    f"- `{PROSE_CRITIC_NAME}`, one per lesson, after drafting. It returns "
    "failed rule numbers and passages. Send those back to a "
    f"`{LESSON_DRAFTER_NAME}` for the same path; do not edit the lesson "
    "yourself.\n"
    f"- `{QUIZ_WRITER_NAME}`, one per lesson, only once that lesson is final. "
    "It writes from the lesson as it stands, so a lesson still in revision "
    "gets items for prose that is about to change.\n"
    f"- `{UNIT_REVIEWER_NAME}`, once, last. It writes `review.md` across the "
    "whole unit.\n\n"
    "The last two belong to the assessment phase, and that phase gets its own "
    "instructions. Do not run them early to save a turn: both read the lessons "
    "as final, and a unit reviewed while a drafter is still revising is a "
    "review of prose that no longer exists.\n\n"
    "One writer per path per phase. Never run two subagents that write the "
    f"same file, and never dispatch a drafter for a lesson while a "
    f"`{QUIZ_WRITER_NAME}` is on it. The subagents cannot see each other, so a "
    "collision is yours to prevent, not theirs to detect."
)
