"""Marking one attempt at one component, where the answer key actually is.

`components.project(view="learner")` strips the answer key out of the payload,
which means the browser is structurally incapable of grading. That is the
design, not an oversight: a client-side check against a key the client was
handed is a ceremony that any reader of the page can step around, and it was
never much less work than doing it properly. So grading lives here, beside the
parse that holds the key, and the browser posts an attempt and is told.

**What a verdict says.** Whether the attempt was correct, a score in `[0, 1]`,
the feedback attached to the choices the learner actually made, and -- once the
attempt is spent -- the rationale and the right answer. Revealing after the
fact is deliberate. Withholding the key before the attempt is what makes the
question a question; withholding it afterwards would only withhold the lesson,
and the whole reason for per-option feedback is that the moment just after a
wrong answer is the one moment the learner is most ready to read it.

**Partial credit is reported and never rounded up.** A multiple-response item
with two of three right scores 0.5 and is *not* correct. The score exists so an
author can see which distractor is doing the work; correctness is set equality,
because a learner who half-knows the answer does not know it.

**Nothing here trusts the request body.** An attempt arrives as untyped JSON
from a browser, so every shape a client might send -- a bare index, a list, a
mapping keyed by blank, `null`, a float, a string where a number belongs --
either grades or raises `GradingError`. It never raises anything else, because
anything else is a 500 on an endpoint a learner can reach.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from research_team.application.components import REGISTRY, ComponentBlock


class GradingError(Exception):
    """The attempt could not be marked, and the reason is the client's to fix.

    Every raise site is a 400 or a 404 at the endpoint, never a 500: a bad
    response shape, an option that does not exist, or a component that is not
    the kind of thing that has a right answer.
    """


@dataclass(frozen=True)
class Verdict:
    """The result of one attempt, and everything the learner has now earned."""

    correct: bool
    score: float
    feedback: list[str] = field(default_factory=list)
    rationale: str | None = None
    correct_options: list[int] | None = None
    blanks: list[dict[str, Any]] | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "correct": self.correct,
            "score": self.score,
            "feedback": self.feedback,
        }
        if self.rationale is not None:
            out["rationale"] = self.rationale
        if self.correct_options is not None:
            out["correct_options"] = self.correct_options
        if self.blanks is not None:
            out["blanks"] = self.blanks
        return out


_WHITESPACE = re.compile(r"\s+")


def normalize_answer(value: Any) -> str:
    """Case and spacing are typing, not knowledge; word choice is knowledge.

    Deliberately stops there. Stemming, synonym sets and edit distance are all
    tempting and all turn a wrong answer into a right one somewhere it matters
    -- "SEV-1" and "SEV-2" are one character apart and mean entirely different
    nights for the on-call director.
    """
    return _WHITESPACE.sub(" ", str(value).strip()).casefold()


def _as_indices(response: Any, count: int) -> list[int]:
    """A bare index, or a list of them. Anything else is the client's problem."""
    if isinstance(response, bool) or response is None:
        raise GradingError("expected an option index or a list of them")
    if isinstance(response, int):
        picks = [response]
    elif isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        picks = []
        for item in response:
            if isinstance(item, bool) or not isinstance(item, int):
                raise GradingError(f"{item!r} is not an option index")
            picks.append(item)
    else:
        raise GradingError("expected an option index or a list of them")
    for pick in picks:
        if not 0 <= pick < count:
            raise GradingError(f"there is no option {pick}; this item has {count}")
    return picks


def _grade_mcq(component: ComponentBlock, response: Any) -> Verdict:
    options = component.data.get("options", [])
    picked = set(_as_indices(response, len(options)))
    key = {i for i, option in enumerate(options) if option.get("correct") is True}

    # Set equality, not overlap. Anything looser marks a learner who selected
    # every option as having answered correctly, which is the oldest way to
    # make an assessment meaningless.
    correct = picked == key

    # Jaccard, so that both a missed answer and a wrong extra cost something.
    # An empty selection against a non-empty key is 0, not a division by zero.
    union = picked | key
    score = 1.0 if not union else len(picked & key) / len(union)

    feedback = [
        str(options[i]["feedback"])
        for i in sorted(picked)
        if isinstance(options[i], Mapping) and options[i].get("feedback")
    ]
    rationale = component.data.get("rationale")
    return Verdict(
        correct=correct,
        score=round(score, 4),
        feedback=feedback,
        rationale=str(rationale) if rationale else None,
        correct_options=sorted(key),
    )


def _as_blank_answers(response: Any, count: int) -> list[str]:
    """A list in blank order, or a mapping keyed by blank index.

    A short list is not an error -- a learner who filled two of four blanks and
    submitted gets those two marked, which is more useful than a 400.
    """
    if isinstance(response, Mapping):
        answers = [""] * count
        for key, value in response.items():
            try:
                index = int(key)
            except (TypeError, ValueError) as error:
                raise GradingError(f"{key!r} is not a blank index") from error
            if not 0 <= index < count:
                raise GradingError(f"there is no blank {index}; this item has {count}")
            answers[index] = "" if value is None else str(value)
        return answers
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        if len(response) > count:
            raise GradingError(f"got {len(response)} answers for {count} blanks")
        given = ["" if v is None else str(v) for v in response]
        return given + [""] * (count - len(given))
    raise GradingError("expected a list of answers, or a mapping keyed by blank")


def _grade_cloze(component: ComponentBlock, response: Any) -> Verdict:
    blanks = [s for s in component.data.get("segments", []) if "blank" in s]
    answers = _as_blank_answers(response, len(blanks))

    results = []
    for blank, given in zip(blanks, answers, strict=True):
        expected = str(blank.get("answer", ""))
        hit = bool(given.strip()) and normalize_answer(given) == normalize_answer(expected)
        # The answer is revealed per blank, having been attempted. A blank left
        # empty is revealed too: the learner submitted, so the item is spent.
        results.append({"blank": blank["blank"], "correct": hit, "answer": expected})

    hits = sum(1 for r in results if r["correct"])
    score = 1.0 if not results else hits / len(results)
    return Verdict(
        correct=bool(results) and hits == len(results),
        score=round(score, 4),
        blanks=results,
    )


_GRADERS = {"mcq": _grade_mcq, "cloze": _grade_cloze}


def grade(component: ComponentBlock, response: Any) -> Verdict:
    """Mark `response` against `component`, or say why it cannot be marked."""
    if component.unknown:
        raise GradingError(f"{component.type!r} is not a component this server knows")
    if component.errors:
        raise GradingError(
            f"component {component.id!r} did not parse, so there is no answer to mark"
        )
    spec = REGISTRY.get(component.type)
    if spec is None or not spec.gradeable:
        raise GradingError(f"a {component.type} is not graded")
    return _GRADERS[component.type](component, response)
