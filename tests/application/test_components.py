"""Reading a lesson: what a component block is, and what happens when it is wrong.

The parser's contract is stated once, in three parts, and nearly every test
here is an instance of one of them.

**Totality.** A document is authored by a model, so malformed input is the
expected case rather than the exceptional one. `parse_document` never raises.
The property test at the bottom is the real statement of this; the examples
above it pin the specific shapes we know a model produces.

**Degradation is per-block, never per-document.** One bad component must cost
exactly one component. A lesson that renders eleven widgets and one error panel
is enormously more useful than a stack trace, and the difference between those
two outcomes is entirely a matter of where the `try` sits. Hence
`test_one_malformed_component_does_not_cost_the_others`.

**Unknown is not an error.** An unrecognised type renders as a labelled code
block -- exactly what the client does with it today, and exactly what the
mermaid pattern promises. This is what keeps the registry free to grow without
every older reader treating a newer lesson as broken.
"""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from research_team.application.components import (
    ComponentBlock,
    MarkdownBlock,
    component_reference,
    derive_id,
    parse_document,
    project,
    validation_report,
)
from research_team.application.graph_read import MAX_NEIGHBORHOOD_DEPTH

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


def _components(doc):
    return [b for b in doc.blocks if isinstance(b, ComponentBlock)]


def test_a_document_with_no_components_is_one_markdown_block():
    doc = parse_document("# Heading\n\nSome prose.\n")
    assert [type(b) for b in doc.blocks] == [MarkdownBlock]
    assert doc.blocks[0].text == "# Heading\n\nSome prose.\n"


def test_a_component_fence_becomes_a_component_block():
    doc = parse_document(MCQ)
    (component,) = _components(doc)
    assert component.type == "mcq"
    assert component.id == "sev-classification-1"
    assert component.errors == ()
    assert component.data["options"][1]["correct"] is True


def test_prose_around_a_component_is_preserved_in_order():
    doc = parse_document(f"Before.\n\n{MCQ}\nAfter.\n")
    kinds = [b.kind for b in doc.blocks]
    assert kinds == ["markdown", "component", "markdown"]
    assert doc.blocks[0].text.strip() == "Before."
    assert doc.blocks[2].text.strip() == "After."


def test_a_bare_type_name_is_still_a_code_block():
    """`component:` is the namespace, and it is the whole point of the prefix.

    An info string of `mcq` could plausibly become a language tag someone adds
    to a highlighter later. Claiming it here would mean a lesson's meaning
    depended on which of the two shipped first.
    """
    doc = parse_document("```mcq\nid: x\n```\n")
    assert _components(doc) == []


def test_an_unknown_type_degrades_to_a_labelled_block_without_error():
    doc = parse_document("```component:widget-from-the-future\nwhatever: 1\n```\n")
    (component,) = _components(doc)
    assert component.unknown is True
    assert component.errors == ()
    assert component.raw == "whatever: 1"
    assert component.lang == "component:widget-from-the-future"


def test_a_known_type_with_unparseable_yaml_keeps_its_raw_body():
    doc = parse_document("```component:mcq\nprompt: : :\n```\n")
    (component,) = _components(doc)
    assert component.unknown is False
    assert component.errors != ()
    assert component.raw == "prompt: : :"


def test_a_known_type_missing_a_required_field_reports_the_field():
    doc = parse_document("```component:mcq\nid: no-options\nprompt: Hi\n```\n")
    (component,) = _components(doc)
    assert [e.path for e in component.errors] == ["options"]
    assert "required" in component.errors[0].message


def test_a_body_that_is_not_a_mapping_is_an_error_not_a_crash():
    doc = parse_document("```component:mcq\n- just\n- a list\n```\n")
    (component,) = _components(doc)
    assert component.errors != ()


def test_one_malformed_component_does_not_cost_the_others():
    """The whole degradation contract, in one assertion."""
    doc = parse_document(f"{MCQ}\n```component:mcq\nbroken: [\n```\n\n{MCQ}")
    good, bad, also_good = _components(doc)
    assert good.errors == () and also_good.errors == ()
    assert bad.errors != ()


def test_frontmatter_is_lifted_off_the_document():
    doc = parse_document("---\ntype: lesson\nstage: 3\n---\n\n# Body\n")
    assert doc.frontmatter == {"type": "lesson", "stage": 3}
    assert "type: lesson" not in doc.blocks[0].text


def test_a_document_with_no_frontmatter_has_none_rather_than_empty():
    """`None` and `{}` mean different things: absent versus present-and-bare."""
    doc = parse_document("# Body\n")
    assert doc.frontmatter is None


def test_tilde_fences_open_components_too():
    doc = parse_document("~~~component:checklist\nid: c\nitems:\n  - text: Go\n~~~\n")
    (component,) = _components(doc)
    assert component.type == "checklist"
    assert component.errors == ()


def test_a_longer_fence_contains_a_shorter_one():
    """A component example inside a documentation block is not a component."""
    doc = parse_document("````markdown\n```component:mcq\nid: x\n```\n````\n")
    assert _components(doc) == []


def test_an_info_string_with_extra_words_still_opens_a_fence():
    """The scanner and the client must agree on where a code block starts.

    `app.js` does not anchor its fence pattern, so ```` ```js {1,3} ```` opens a
    block in the browser. If this scanner disagreed and read that line as prose,
    it would keep scanning *inside* the code sample -- and a `component:` fence
    shown as an example within it would be extracted as a real component.
    """
    doc = parse_document("```js {1,3}\n```component:mcq\nid: x\n```\n")
    assert _components(doc) == []


def test_a_code_fence_survives_the_round_trip_unaltered():
    """Non-component fences are handed back verbatim, attributes and all."""
    source = "```js {1,3} title=demo\nconst a = 1;\n```\n"
    doc = parse_document(source)
    assert doc.blocks[0].text == source


def test_an_unclosed_component_fence_still_parses_what_it_has():
    doc = parse_document("```component:checklist\nid: c\nitems:\n  - text: Go\n")
    (component,) = _components(doc)
    assert component.errors == ()


def test_a_missing_id_is_derived_and_warned_about():
    """A derived id is stable across re-renders, and only across re-renders.

    It is `sha256(path + index)`, so an edit *above* the component does not
    move it but an insert does. That is worth a warning rather than an error:
    the lesson renders, and the author is told the one thing that will bite
    them later.
    """
    source = "```component:checklist\nitems:\n  - text: Go\n```\n"
    doc = parse_document(source, path="/course/03.md")
    (component,) = _components(doc)
    assert component.id == derive_id("/course/03.md", 0)
    assert component.errors == ()
    assert any("id" in w.path for w in component.warnings)


def test_derived_ids_differ_by_position_and_by_path():
    assert derive_id("/a.md", 0) != derive_id("/a.md", 1)
    assert derive_id("/a.md", 0) != derive_id("/b.md", 0)


def test_a_duplicate_id_is_reported_because_learner_state_keys_on_it():
    doc = parse_document(f"{MCQ}\n{MCQ}")
    first, second = _components(doc)
    assert first.warnings == ()
    assert any("duplicate" in w.message for w in second.warnings)


# --- properties -----------------------------------------------------------
#
# Built from fragments rather than an alphabet so fences, colons and frontmatter
# markers are generated as units. Free text alone essentially never produces a
# well-formed fence, and it is the fence handling that has the sharp edges.
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


@given(DOCUMENT)
def test_parsing_is_total(text):
    """No input raises. The corpus is model-authored; this is not optional."""
    doc = parse_document(text, path="/course/01.md")
    assert doc.blocks is not None


@given(DOCUMENT)
def test_every_component_block_is_identifiable_and_degradable(text):
    """Whatever comes out, the renderer can dispatch on it.

    Three invariants the client relies on and cannot defend itself against: a
    type is always present, an id is always present (derived if absent) because
    it is the key learner state will hang off, and the raw body survives so an
    error panel has something to show.
    """
    for block in parse_document(text, path="/course/01.md").blocks:
        if isinstance(block, ComponentBlock):
            assert block.type
            assert block.id
            assert block.raw is not None


@given(DOCUMENT)
def test_no_content_is_silently_dropped(text):
    """Every line of the source lands in some block.

    A viewer that quietly eats a line is worse than one that renders it wrong,
    because nothing on the page says anything is missing.

    Frontmatter is excluded rather than asserted over: it is lifted off the
    document by design, so its lines legitimately do not appear in any block.
    """
    assume(not text.startswith("---"))
    doc = parse_document(text, path="/course/01.md")
    seen = "".join(b.text if isinstance(b, MarkdownBlock) else b.raw for b in doc.blocks)
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith(("```", "~~~", "---")):
            assert line.strip() in seen


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


CLOZE = """\
```component:cloze
id: comms-cadence
text: |
  A {{SEV-1}} needs an update every {{15 minutes::how often?}}.
```
"""


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


# --- authoring feedback ---------------------------------------------------


def test_a_clean_document_reports_nothing():
    assert validation_report(parse_document(MCQ)) == ""


def test_the_report_names_the_component_the_field_and_the_problem():
    report = validation_report(parse_document("```component:mcq\nid: q\nprompt: Hi\n```\n"))
    assert "'q'" in report and "options" in report and "required" in report


def test_an_unknown_type_is_not_reported_as_a_problem():
    """Registering a type later must not retroactively make old lessons wrong."""
    assert validation_report(parse_document("```component:from-the-future\nx: 1\n```\n")) == ""


# --- knowing when to reach for one -----------------------------------------
#
# A syntax reference alone is a grammar with no occasion. These pin the other
# half: that a stage writing an assessment artifact is told which components an
# assessment is made of, and -- just as importantly -- that a stage writing a
# source claim is told nothing, because 2kB of widget syntax in an intake
# stage's prompt is 2kB of noise it will never act on.


def test_a_stage_that_writes_no_component_bearing_artifact_gets_no_guidance():
    from research_team.application.components import component_guidance
    from research_team.domain.workflow import ArtifactType, StageOutput

    outputs = (StageOutput(artifact_type=ArtifactType.SOURCE_CLAIM, cardinality="1..n"),)
    assert component_guidance(outputs) == ""


def test_an_evidence_stage_is_pointed_at_the_assessment_components():
    from research_team.application.components import component_guidance
    from research_team.domain.workflow import ArtifactType, StageOutput

    outputs = (
        StageOutput(
            artifact_type=ArtifactType.EVIDENCE_SPEC,
            subtype="assessment_item",
            cardinality="1..n",
        ),
    )
    guidance = component_guidance(outputs)

    assert "EvidenceSpec" in guidance
    assert "mcq" in guidance
    # The deck belongs in a learning plan, not in the evidence an assessment is.
    assert "flashcards" not in guidance.split("### mcq")[0]


def test_a_learning_plan_is_pointed_at_practice_rather_than_assessment():
    from research_team.application.components import component_guidance
    from research_team.domain.workflow import ArtifactType, StageOutput

    outputs = (StageOutput(artifact_type=ArtifactType.EXPERIENCE, cardinality="1..n"),)
    guidance = component_guidance(outputs)

    assert "Experience" in guidance
    assert "flashcards" in guidance and "checklist" in guidance


def test_guidance_carries_the_syntax_reference_so_the_two_arrive_together():
    """Knowing a component fits and not knowing how to write one is no better
    than the reverse, so they are one block or neither."""
    from research_team.application.components import component_guidance
    from research_team.domain.workflow import ArtifactType, StageOutput

    outputs = (StageOutput(artifact_type=ArtifactType.BUILD, cardinality="1"),)
    guidance = component_guidance(outputs)

    assert "```component:mcq" in guidance
    assert "block scalar" in guidance


def test_every_component_named_in_the_map_is_actually_registered():
    """The map is prose handed to a model; an unregistered name in it would be
    an instruction to write a component that renders as a code block."""
    from research_team.application.components import COMPONENTS_FOR, REGISTRY

    for artifact, names in COMPONENTS_FOR.items():
        assert names, f"{artifact} maps to nothing; drop the entry instead"
        for name in names:
            assert name in REGISTRY, f"{artifact} names unregistered {name!r}"


def test_the_generated_reference_covers_every_registered_type():
    """The reference is generated so it cannot drift from the schemas.

    Each example is parsed back through the parser, which makes this a real
    check on the registry rather than a check that some strings exist: an
    example that stopped satisfying its own schema fails here.
    """
    from research_team.application.components import REGISTRY

    reference = component_reference()
    for name, component in REGISTRY.items():
        assert name in reference
        parsed = parse_document(component.example)
        assert parsed.components, f"{name}'s example does not parse as a component"
        assert parsed.components[0].errors == (), f"{name}'s own example is invalid"
        assert parsed.components[0].type == name


def test_the_reference_carries_each_type_s_craft_notes():
    """The generated reference is the only place either agent learns to write
    a good item, so craft travels with syntax or not at all.

    Reverting `craft` to a field nothing renders leaves this red: the strings
    are in the registry either way, and `component_reference` is what has to
    put them in front of a model.
    """
    reference = component_reference(only=["mcq"])

    assert "distractor" in reference
    # "feedback" alone doesn't discriminate: mcq's summary and example both
    # already said it before craft existed, so it passes with craft rendered
    # or reverted. This phrase is only in the craft note itself.
    assert "misunderstanding that makes it attractive" in reference


def test_craft_notes_are_scoped_to_the_types_asked_for():
    """`only` narrows craft the same way it narrows examples -- showing a stage
    how to write a good cloze it was told not to use is the same mistake the
    `only` parameter exists to prevent."""
    reference = component_reference(only=["flashcards"])

    assert "one fact per card" in reference.lower()
    assert "distractor" not in reference


# --- B31: the guidance has to survive being handed to a subagent ------------
#
# Component guidance rides `StageMiddleware`, which wraps the *caller's* model
# call. A subagent spawned through `task` gets `delegation.py`'s own static
# system prompt and none of this, so a delegated "draft the assessment items"
# comes back as prose no renderer will use -- and it fails silently, looking
# like a model that ignored instructions it was genuinely never given.
#
# The fix is the cheaper of B31's two options: tell the *caller* to put the
# requirement in the task it writes. That is consistent with delegation.py's
# own "give it everything it needs; it cannot see this conversation", and it
# keeps the subagent prompt static so every delegation does not pay for
# guidance most of them have no use for.


def test_a_component_stage_is_told_to_carry_the_requirement_into_a_delegated_task():
    from research_team.application.components import component_guidance
    from research_team.domain.workflow import ArtifactType, StageOutput

    outputs = (
        StageOutput(
            artifact_type=ArtifactType.EVIDENCE_SPEC,
            subtype="assessment_item",
            cardinality="1..n",
        ),
    )
    guidance = component_guidance(outputs)

    assert "delegate" in guidance.lower()
    # Naming the tool matters: "delegate" alone is a concept, `task` is the
    # thing the model actually calls.
    assert "task" in guidance.lower()
    # The instruction has to be to restate the requirement, not merely to know
    # that subagents exist.
    assert "cannot see" in guidance.lower()


def test_a_stage_with_no_components_is_told_nothing_about_delegation_either():
    """The delegation note is part of the component block, not a new always-on
    paragraph. A stage writing source claims has no component requirement to
    carry into a subagent task, so there is nothing here for it to be told."""
    from research_team.application.components import component_guidance
    from research_team.domain.workflow import ArtifactType, StageOutput

    outputs = (StageOutput(artifact_type=ArtifactType.SOURCE_CLAIM, cardinality="1..n"),)
    assert component_guidance(outputs) == ""


# --- B29: the parse was nine times slower than it needed to be -------------
#
# B29 recorded "the parse is not cached, though the cache key is exact", and
# deferred the cache because nothing had measured it. Measuring it found
# something better than a cache: `yaml.safe_load` binds PyYAML's *pure-Python*
# scanner even when the libyaml extension is installed, and on this machine the
# C loader parses the same component body ~9x faster. A cache over the slow
# loader would have bought less and cost an invalidation story.
#
# So these pin the substitution rather than a speed: that we take the C loader
# when it exists, that it is still a *safe* loader, and that a malformed body
# still degrades into a Note rather than an exception.


def test_the_c_yaml_loader_is_used_when_the_extension_is_available():
    """Not a benchmark -- benchmarks are flaky on a loaded machine. This pins
    the decision that produced the speedup, which is the durable part."""
    import yaml

    from research_team.application.components import _YAML_LOADER

    if hasattr(yaml, "CSafeLoader"):
        assert _YAML_LOADER is yaml.CSafeLoader
    else:
        assert _YAML_LOADER is yaml.SafeLoader


def test_the_loader_is_still_a_safe_one():
    """The whole point of `safe_load` is that a lesson written by a model cannot
    construct arbitrary Python. Swapping the loader for speed must not swap that
    away -- `yaml.CLoader` is also faster and would."""
    doc = parse_document(
        "```component:mcq\n!!python/object/apply:os.system ['echo pwned']\n```\n"
    )
    block = doc.blocks[0]
    assert block.kind == "component"
    assert block.errors, "an unsafe tag must be refused, not constructed"


@pytest.mark.parametrize(
    "body",
    [
        "options: [1, 2",
        "a:\n- b\n  c: 1",
        "*undefined",
        "a: |\n\ttab",
    ],
)
def test_a_malformed_body_still_degrades_rather_than_raising(body):
    """The C loader words its complaints differently from the pure-Python one.
    What must not change is that every one of them arrives as a Note on the
    block -- the authoring feedback loop reads these."""
    doc = parse_document(f"```component:mcq\n{body}\n```\n")
    block = doc.blocks[0]
    assert block.kind == "component"
    assert block.errors
    message = str(block.errors[0])
    assert "could not parse the YAML body" in message
    # Non-empty detail: an error that says only "could not parse" tells the
    # model nothing it can act on.
    assert message.split("--", 1)[1].strip()


DEFINITION = """\
```component:definition
id: nicene
entity: Nicene Christianity
```
"""


def test_a_definition_carries_its_reference_through_both_views():
    """The body is a query, so there is nothing to strip and nothing to grade.

    Red against a `definition` entry that sets `gradeable=True` or a `strip`,
    both of which are the shape every other registered type has and therefore
    the shape a copy-paste addition would arrive in.
    """
    document = parse_document(DEFINITION, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert author["data"]["entity"] == "Nicene Christianity"
    assert learner["data"] == author["data"]
    assert learner["resolved"] is True
    assert learner["gradeable"] is False


def test_a_definition_without_an_entity_says_which_field_is_missing():
    source = "```component:definition\nid: nope\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == ["entity: required field missing"]


def test_a_definition_may_pin_an_ambiguous_name_with_an_entity_id():
    """`entity_id` is the escape hatch, and it is *not* a warned-about unknown
    key -- a human copying one out of the console must not be told the field
    they were told to use is unrecognised."""
    source = (
        "```component:definition\n"
        "id: c\n"
        "entity: Constantine\n"
        "entity_id: 8f2c1e00-0000-4000-8000-000000000000\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert block.warnings == ()
    assert block.data["entity_id"] == "8f2c1e00-0000-4000-8000-000000000000"


def test_the_generated_reference_renders_the_definition_example():
    """`component_reference` is what the authoring model reads. A type whose
    example does not appear in it is a type the model will never write."""
    reference = component_reference(only=["definition"])

    assert "component:definition" in reference
    assert "entity:" in reference


EVIDENCE = """\
```component:evidence
id: state-religion
claim: |
  Theodosius made Nicene Christianity the state religion in AD 380.
sources:
  - source: doc-1
    start: 4120
    end: 4380
```
"""


def test_evidence_carries_its_claim_and_ranges_through_both_views():
    """Red against an `evidence` entry that strips or grades.

    There is no answer key to withhold here -- the claim and the passages
    behind it are the whole body -- and the widget's entire value is that the
    reader compares the two, so a learner who sees less than the author does
    cannot do the one thing this component exists for.
    """
    document = parse_document(EVIDENCE, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["sources"][0] == {"source": "doc-1", "start": 4120, "end": 4380}
    assert learner["resolved"] is True


def test_evidence_needs_at_least_one_source():
    """A claim with no passage behind it is prose wearing a widget's clothes,
    and the widget's entire value is that the reader can check it."""
    source = "```component:evidence\nid: e\nclaim: Something happened.\nsources: []\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "sources: expected at least 1 entry, got 0"
    ]


def test_evidence_names_the_offending_source_by_its_subscript():
    source = (
        "```component:evidence\n"
        "id: e\n"
        "claim: Something happened.\n"
        "sources:\n"
        "  - start: 10\n"
        "    end: 20\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "sources[0].source: required field missing"
    ]


def test_evidence_refuses_a_negative_offset():
    """Red against `Spec(text)` on the offsets, which would accept `start: -5`
    and send it to a route that clamps it to 0 without saying so."""
    source = (
        "```component:evidence\n"
        "id: e\n"
        "claim: Something happened.\n"
        "sources:\n"
        "  - source: doc-1\n"
        "    start: -5\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "sources[0].start: expected a whole number from 0 to 100000000, got -5"
    ]


GRAPH = """\
```component:graph
id: constantine-around
entity: Constantine
depth: 1
```
"""


def test_a_graph_carries_its_reference_and_depth_through_both_views():
    document = parse_document(GRAPH, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["depth"] == 1
    assert learner["resolved"] is True


def test_a_graph_defaults_its_depth_to_one():
    """One hop is the readable neighbourhood; two is a hairball in a markdown
    column. Red against a registry entry with no `default`, which would leave
    `depth` absent and the client picking a second bound to keep in step."""
    source = "```component:graph\nid: g\nentity: Constantine\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert block.data["depth"] == 1


def test_a_graph_depth_past_the_server_s_bound_is_an_authoring_error():
    """The route answers 422 for this (`app.py`'s `read_graph_neighborhood`).
    Catching it here turns a failure the reader would meet into a note the
    model can act on, which is what the validation report exists for. Red
    against `Spec(text)` on `depth`."""
    source = "```component:graph\nid: g\nentity: Constantine\ndepth: 5\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "depth: expected a whole number from 1 to 2, got 5"
    ]


def test_a_graph_depth_bound_tracks_the_server_s_constant():
    """Red against a hardcoded `2` in the registry the day someone raises
    `MAX_NEIGHBORHOOD_DEPTH` -- the failure being a widget that validates to
    one bound and fetches against another, which nothing else would report."""
    source = (
        f"```component:graph\nid: g\nentity: Constantine\n"
        f"depth: {MAX_NEIGHBORHOOD_DEPTH}\n```\n"
    )

    assert parse_document(source, path="lesson.md").components[0].errors == ()
