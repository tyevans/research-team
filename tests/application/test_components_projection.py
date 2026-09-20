"""Tests for component view projections.

Author vs Learner projections and answer key redaction.
"""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from research_team.application.components import (
    parse_document,
    project,
)

DOCUMENT = st.lists(
    st.sampled_from(
        [
            "# Heading\n",
            "prose\n",
            "\n",
            "---\n",
            "```\n",
            "````\n",
            "~~~\n",
            "```component:mcq\n",
            "```component:unknown-type\n",
            "~~~component:checklist\n",
            "id: x\n",
            "prompt: |\n",
            "  text\n",
            "- item\n",
            ": : :\n",
            "\t\n",
        ]
    ),
    max_size=25,
).map("".join)

MCQ = """\
```component:mcq
id: sev-classification-1
prompt: |
  What severity?
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

CLOZE = """\
```component:cloze
id: comms-cadence
text: |
  A {{SEV-1}} needs an update every {{15 minutes::how often?}}.
```
"""


@pytest.mark.parametrize("view", ["author", "learner"])
@given(DOCUMENT)
def test_projection_is_total_for_both_views(view, text):
    assert project(parse_document(text, path="/x.md"), view=view)["blocks"] is not None


# --- the learner projection -----------------------------------------------


def _block(doc, view):
    return project(doc, view=view)["blocks"][0]


def test_the_author_sees_the_answer_key():
    block = _block(parse_document(MCQ), "author")
    assert block["data"]["options"][1]["correct"] is True
    assert "rationale" in block["data"]
    assert block["withheld"] == []


def test_the_learner_sees_options_without_which_one_is_right():
    block = _block(parse_document(MCQ), "learner")
    assert [o["text"] for o in block["data"]["options"]] == ["SEV-1", "SEV-2"]
    assert all("correct" not in o and "feedback" not in o for o in block["data"]["options"])
    assert "rationale" not in block["data"]
    assert "options[].correct" in block["withheld"]


def test_the_learner_still_sees_the_prompt():
    """Withholding is surgical. A question with no question is not a question."""
    assert "What severity?" in _block(parse_document(MCQ), "learner")["data"]["prompt"]


def test_a_cloze_is_normalised_into_segments_at_parse_time():
    """The answers are the prose, so they have to be separated before shipping."""
    data = _block(parse_document(CLOZE), "author")["data"]
    assert data["blanks"] == 2
    blanks = [s for s in data["segments"] if "blank" in s]
    assert [b["answer"] for b in blanks] == ["SEV-1", "15 minutes"]
    assert blanks[1]["hint"] == "how often?"


def test_the_learner_gets_the_hint_and_never_the_answer():
    data = _block(parse_document(CLOZE), "learner")["data"]
    blanks = [s for s in data["segments"] if "blank" in s]
    assert all("answer" not in b for b in blanks)
    assert blanks[1]["hint"] == "how often?"
    assert "text" not in data, "the source text would hand back every answer at once"


def test_a_learner_projection_carries_no_raw_body_for_a_valid_component():
    assert "raw" not in _block(parse_document(MCQ), "learner")


def test_a_broken_component_keeps_its_raw_body_even_for_a_learner():
    """There is no answer key in a block that failed to parse, and the panel
    has to show the author something when they are the one reading."""
    doc = parse_document("```component:mcq\nbroken: [\n```\n")
    assert "raw" in _block(doc, "learner")


def test_ungraded_types_are_marked_as_such():
    checklist = "```component:checklist\nid: c\nitems:\n  - text: Go\n```\n"
    assert _block(parse_document(checklist), "learner")["gradeable"] is False
    assert _block(parse_document(MCQ), "learner")["gradeable"] is True


# Drawn from disjoint alphabets so that "the secret did not leak" and "the
# secret happened to be a substring of something public" cannot be confused.
# Filtering those collisions out with `assume` instead would work, but it would
# make the test weaker exactly where the generator got interesting.
# Each is also tagged, so a one-character body cannot accidentally match the
# structural text of the payload -- an answer of "x" is "in" the path "/x.md",
# which says nothing about whether the projection works.
def _tagged(tag: str, alphabet: str):
    return (
        st.text(alphabet=alphabet, min_size=1, max_size=20)
        .map(lambda s: f"{tag}{s.strip()}")
        .filter(lambda s: len(s) > len(tag))
    )


VISIBLE = _tagged("shown-", "abc ")
SECRET = _tagged("secret-", "xyz ")


@given(right=VISIBLE, wrong=VISIBLE, why=SECRET)
def test_no_mcq_answer_key_survives_the_learner_projection(right, wrong, why):
    """The property the whole projection exists to provide.

    Asserted over the serialised payload rather than over the fields, because
    the failure that matters is a secret reaching the wire by any route -- a
    field nobody thought to strip, a copy left in a sibling key, a
    normalisation step that helpfully preserved the original. Checking the
    bytes catches all three; checking `data["options"][i]` catches none of them.
    """
    assume(right.strip() != wrong.strip())
    source = (
        "```component:mcq\n"
        "id: q\n"
        'prompt: "pick one"\n'
        "options:\n"
        f'  - text: "{wrong}"\n'
        "    correct: false\n"
        f'    feedback: "{why}"\n'
        f'  - text: "{right}"\n'
        "    correct: true\n"
        "rationale: |\n"
        f"  {why}\n"
        "```\n"
    )
    doc = parse_document(source, path="/x.md")
    assume(doc.components[0].ok)

    learner = repr(project(doc, view="learner"))
    assert why.strip() not in learner, "feedback or rationale leaked"
    assert "'correct'" not in learner, "the answer key leaked"
    # And the control: the author view does carry it, so a projection that
    # simply dropped everything would not pass this test either.
    assert why.strip() in repr(project(doc, view="author"))


@given(answer=SECRET, hint=VISIBLE)
def test_no_cloze_answer_survives_the_learner_projection(answer, hint):
    source = f"```component:cloze\nid: c\ntext: |\n  Fill {{{{{answer}::{hint}}}}} in.\n```\n"
    doc = parse_document(source, path="/x.md")
    assume(doc.components[0].ok and doc.components[0].data["blanks"] == 1)

    learner = repr(project(doc, view="learner"))
    assert answer.strip() not in learner
    assert hint.strip() in learner, "the hint is the whole affordance; it must survive"
