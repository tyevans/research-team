"""Marking an attempt, on the server, because the client was not given the key.

This module only exists because of a decision made in `components.py`: the
learner projection strips the answers, so the browser *cannot* grade even if we
wanted it to. That is the point. Grading here is not extra ceremony on top of a
client-side check, it is the only implementation there is.

Two things the tests below pin down that are easy to get wrong.

**Feedback is returned for the option the learner actually chose**, not for the
right one. "Retries succeed, so a workaround exists" earns its place by
explaining *this* learner's reasoning back to them; a generic "incorrect" does
not.

**The answer is revealed once the attempt is spent.** Withholding it before the
attempt is what makes the question a question; withholding it afterwards would
just be withholding the lesson. So a graded response carries the rationale and
which options were right, and `test_a_wrong_answer_still_teaches` says so.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_team.application.components import parse_document
from research_team.application.grading import GradingError, grade

MCQ = """\
```component:mcq
id: sev-1
prompt: What severity?
options:
  - text: "SEV-1"
    correct: false
    feedback: "No data loss."
  - text: "SEV-2"
    correct: true
    feedback: "Textbook SEV-2."
rationale: |
  Severity is a communication decision.
```
"""

MULTI = """\
```component:mcq
id: multi
prompt: Which are true?
multiple: true
options:
  - text: "a"
    correct: true
  - text: "b"
    correct: false
  - text: "c"
    correct: true
```
"""

CLOZE = """\
```component:cloze
id: cadence
text: |
  A {{SEV-1}} updates every {{15 minutes::how often?}}.
```
"""


def _component(source, index=0):
    return parse_document(source).components[index]


def test_the_right_option_is_correct():
    verdict = grade(_component(MCQ), 1)
    assert verdict.correct is True
    assert verdict.score == 1.0


def test_the_wrong_option_is_not():
    assert grade(_component(MCQ), 0).correct is False


def test_feedback_is_for_the_option_the_learner_chose():
    assert grade(_component(MCQ), 0).feedback == ["No data loss."]
    assert grade(_component(MCQ), 1).feedback == ["Textbook SEV-2."]


def test_a_wrong_answer_still_teaches():
    """The attempt is spent; withholding the answer now teaches nothing."""
    verdict = grade(_component(MCQ), 0)
    assert verdict.correct is False
    assert "communication decision" in verdict.rationale
    assert verdict.correct_options == [1]


def test_a_single_choice_accepts_a_bare_index_or_a_list_of_one():
    """Be liberal here. The shape a client sends is not the learner's fault."""
    assert grade(_component(MCQ), 1).correct is True
    assert grade(_component(MCQ), [1]).correct is True


def test_a_multiple_choice_needs_every_right_answer_and_no_wrong_one():
    assert grade(_component(MULTI), [0, 2]).correct is True
    assert grade(_component(MULTI), [2, 0]).correct is True, "order is not meaning"
    assert grade(_component(MULTI), [0]).correct is False, "incomplete is not correct"
    assert grade(_component(MULTI), [0, 1, 2]).correct is False, "shotgunning is not correct"


def test_a_multiple_choice_scores_partial_credit_without_calling_it_correct():
    """Partial credit is information for the author, not a pass for the learner."""
    verdict = grade(_component(MULTI), [0])
    assert verdict.correct is False
    assert 0 < verdict.score < 1


def test_selecting_nothing_is_wrong_rather_than_an_error():
    verdict = grade(_component(MULTI), [])
    assert verdict.correct is False and verdict.score == 0.0


def test_an_out_of_range_option_is_rejected():
    with pytest.raises(GradingError):
        grade(_component(MCQ), 7)


def test_a_response_of_the_wrong_shape_is_rejected():
    with pytest.raises(GradingError):
        grade(_component(MCQ), {"pick": "SEV-2"})


def test_every_cloze_blank_is_marked_separately():
    verdict = grade(_component(CLOZE), ["SEV-1", "15 minutes"])
    assert verdict.correct is True
    assert verdict.blanks == [
        {"blank": 0, "correct": True, "answer": "SEV-1"},
        {"blank": 1, "correct": True, "answer": "15 minutes"},
    ]


def test_a_cloze_is_forgiving_about_case_and_spacing_but_not_about_words():
    """A learner who typed the right thing should not lose to a stray space."""
    assert grade(_component(CLOZE), ["sev-1", "  15   MINUTES "]).correct is True
    assert grade(_component(CLOZE), ["SEV-2", "15 minutes"]).correct is False


def test_a_partly_filled_cloze_reveals_only_what_was_attempted_wrong():
    verdict = grade(_component(CLOZE), ["SEV-1", "an hour"])
    assert verdict.correct is False
    assert verdict.score == 0.5
    assert verdict.blanks[1]["answer"] == "15 minutes"


def test_a_cloze_accepts_answers_keyed_by_blank():
    assert grade(_component(CLOZE), {"0": "SEV-1", "1": "15 minutes"}).correct is True


def test_a_short_cloze_response_marks_the_missing_blanks_wrong():
    verdict = grade(_component(CLOZE), ["SEV-1"])
    assert verdict.correct is False
    assert verdict.blanks[1]["correct"] is False


def test_an_ungradeable_component_says_so():
    checklist = _component("```component:checklist\nid: c\nitems:\n  - text: Go\n```\n")
    with pytest.raises(GradingError, match="not graded"):
        grade(checklist, True)


def test_a_component_that_did_not_parse_cannot_be_graded():
    broken = _component("```component:mcq\nid: b\nprompt: Hi\n```\n")
    with pytest.raises(GradingError):
        grade(broken, 0)


def test_an_unknown_component_cannot_be_graded():
    unknown = _component("```component:from-the-future\nx: 1\n```\n")
    with pytest.raises(GradingError):
        grade(unknown, 0)


# --- properties -----------------------------------------------------------


@given(
    response=st.one_of(
        st.integers(),
        st.text(max_size=5),
        st.lists(st.integers(), max_size=4),
        st.lists(st.text(max_size=5), max_size=4),
        st.dictionaries(st.text(max_size=3), st.text(max_size=5), max_size=3),
        st.none(),
        st.booleans(),
        st.floats(allow_nan=True, allow_infinity=True),
    ),
    source=st.sampled_from([MCQ, MULTI, CLOZE]),
)
def test_grading_either_marks_or_refuses_and_never_crashes(response, source):
    """An endpoint is on the other side of this, so a crash is a 500.

    Every input is either a verdict or a `GradingError` the endpoint turns into
    a 400. Nothing else escapes -- in particular not a `TypeError` from a
    response shape nobody anticipated, which is precisely what an untyped JSON
    body will eventually deliver.
    """
    try:
        verdict = grade(_component(source), response)
    except GradingError:
        return
    assert isinstance(verdict.correct, bool)
    assert 0.0 <= verdict.score <= 1.0


@given(picks=st.lists(st.integers(min_value=0, max_value=2), max_size=4, unique=True))
def test_correctness_is_exactly_the_right_set(picks):
    """`correct` is set equality and nothing else -- no near-misses pass."""
    verdict = grade(_component(MULTI), sorted(picks))
    assert verdict.correct == (set(picks) == {0, 2})
