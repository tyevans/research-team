"""The project's own extraction domain, and the one field it exists to ask for.

This module's whole reason for being is a single omission upstream: **no
bundled redstring schema mentions `temporal_expression`**, the field
`ExtractionPipeline` reads to build an entity's `TemporalExtent`. Verified by
`grep -rli temporal_expression` over `redstring/extraction/domains/schemas/`,
which matches zero files, and over `DEFAULT_SYSTEM_PROMPT`, which lists six
entity kinds and no dates.

The consequence was measured against the real database on 2026-08-15 before
any of this existed: 214 extracted entities, **zero** carrying a temporal
extent, while 17 separate entities of type `date` stood on the graph holding
dates in their *names* (`1945`, `February 8, 2024`, `19th century`). The
timeline endpoint answered `{"bands": [], "undated_count": 202}` -- correct,
and empty, because nothing upstream had ever been asked for the input it
needs.

So these tests assert the *prompt's content*, which is unusual and deliberate.
Prose is normally not worth testing. Here the prose is the entire fix: every
component below it -- `parse_temporal`, `_build_extent`, `extent_bounds`,
`ProjectTimelineReader` -- already worked and was waiting on a field the model
was never told to fill.
"""

from pathlib import Path

import pytest
from redstring import AUTO, DomainSchema, domain_system_prompt

from research_team.infrastructure.knowledge.domain_schemas import (
    RESEARCH_CORPUS,
    SCHEMA_DIR,
    resolve_domain,
)


def test_auto_still_resolves_to_the_classifier():
    """`auto` keeps its meaning, so the env override is not a one-way door.

    `AGENT_KNOWLEDGE_DOMAIN=auto` was the default before this change and has
    to keep working: switching the default is a decision this project can
    revisit, and a resolver that could only produce its own schema would make
    that revisit a code change.
    """
    assert resolve_domain("auto") is AUTO


def test_a_bundled_redstring_id_passes_straight_through():
    """An id we do not own is redstring's to resolve, not ours to intercept.

    Passed through as a `str` rather than loaded here: `build_graph` resolves
    ids against its own registry, and a resolver that tried to load them would
    have to track the bundled set as it changes across a pre-1.0 minor.
    """
    assert resolve_domain("encyclopedia_wiki") == "encyclopedia_wiki"


def test_the_projects_own_id_resolves_to_a_loaded_schema():
    """The one id that becomes an object rather than a string."""
    resolved = resolve_domain(RESEARCH_CORPUS)
    assert isinstance(resolved, DomainSchema)
    assert resolved.domain_id == RESEARCH_CORPUS


def test_the_schema_file_is_loaded_from_an_absolute_path():
    """A relative path would silently read redstring's directory instead.

    `load_schema_from_file` resolves a relative path **against the bundled
    schema directory**, documented at
    `https://tyevans.github.io/redstring/how-to/author-a-domain-schema/`. So a
    relative path here does not fail loudly -- it looks inside `site-packages`
    for a file that is not there, and the error names redstring's own
    directory rather than ours. This asserts the path we hand over is
    absolute, which is what keeps that failure mode unreachable.
    """
    assert SCHEMA_DIR.is_absolute()
    assert (SCHEMA_DIR / f"{RESEARCH_CORPUS}.yaml").is_file()


def test_the_schema_declares_no_date_entity_type():
    """A date is a property of an event, not a thing that has relationships.

    `encyclopedia_wiki.yaml:102` declares exactly such a type -- "A specific
    date or time period" -- and `AUTO` falls back to that schema on a
    low-confidence classification. That invitation is why 17 date-nodes are
    sitting on the real graph instead of 17 dated entities.

    Necessary and *not sufficient*: redstring's own guide states the schema
    "shapes prompts but does not enforce output -- nothing rejects extracted
    types you never declared". Removing the type stops the model being asked
    for date-nodes; only the prompt prose asserted below tells it not to
    volunteer them anyway.
    """
    schema = resolve_domain(RESEARCH_CORPUS)
    assert isinstance(schema, DomainSchema)
    declared = {entity.id for entity in schema.entity_types}
    assert "date" not in declared


def test_the_rendered_prompt_asks_for_temporal_expression_by_name():
    """The assertion the timeline actually depends on.

    Asserted against `domain_system_prompt(schema)` -- what the model is sent
    -- rather than against the template, because `{entity_descriptions}` is
    substituted in between and a placeholder typo renders as itself. Delete
    the temporal paragraph from the YAML and this is the test that goes red;
    every other test in this file would stay green, and so would the whole
    timeline suite, because they are all fed hand-built extents.
    """
    schema = resolve_domain(RESEARCH_CORPUS)
    assert isinstance(schema, DomainSchema)
    prompt = domain_system_prompt(schema)
    assert "temporal_expression" in prompt


def test_the_rendered_prompt_forbids_dates_as_entities():
    """The other half, and the half a missing entity type cannot enforce.

    Kept as a separate test from the field-name one above because they fail
    for different reasons and a reader of a red run should be told which.
    """
    prompt = domain_system_prompt(resolve_domain(RESEARCH_CORPUS)).lower()
    assert "never" in prompt and "date" in prompt


def test_an_unknown_id_is_refused_here_rather_than_at_ingest():
    """A typo should fail at construction, not four minutes into a document.

    `build_graph` would raise `UnknownDomainError` on a bad id eventually, but
    it raises it *per ingest*, after the document has been stored and the
    first chunks dispatched. Refusing at resolve time moves the failure to
    process start, where a misconfigured deployment is one line in a log
    rather than an ingest that dies partway.
    """
    with pytest.raises(ValueError, match="unknown"):
        resolve_domain("encylopedia_wiki")


def test_every_schema_in_the_directory_loads():
    """`extra: forbid` means a typo'd field name is a load failure, not a shrug.

    Written as a sweep over the directory rather than naming the one file, so
    a second schema added later cannot be added untested.
    """
    for path in sorted(SCHEMA_DIR.glob("*.yaml")):
        assert isinstance(resolve_domain(Path(path).stem), DomainSchema)


class TestTheRelationshipVocabularyIsOpen:
    """The eight declared types are examples, not a closed set.

    Measured against the real database on 2026-08-23: 3,233 relationships, of
    which **6** used a name outside the declared eight -- 0.19%. Extraction
    was never enum-constrained, so nothing was stopping the model naming a
    relationship. A list of eight rendered as a list of eight simply reads as
    exhaustive.

    With 39% of entities isolated and 0.57 edges per entity, an edge the model
    declines to state is the failure mode that matters, so the schema now says
    what it means.
    """

    def test_no_relationship_type_constrains_its_endpoints(self):
        """`prompt_generator` renders these as "(from: person; to: work)",
        which makes `created` unstateable between a work and a concept -- so
        "Star Trek created the Borg" has no legal form and is dropped rather
        than renamed. This is the sharper half of the constraint and the
        reason the change is not only prose."""
        schema = resolve_domain(RESEARCH_CORPUS)

        for relationship_type in schema.relationship_types:
            assert not relationship_type.valid_source_types, relationship_type.id
            assert not relationship_type.valid_target_types, relationship_type.id

    def test_the_prompt_invites_a_name_the_list_does_not_have(self):
        """Deleting the constraints is not enough on its own: redstring's own
        guide is explicit that a schema "shapes prompts but does not enforce
        output", so the invitation has to be stated outright -- the same
        two-halves argument the date rules in this file's header make."""
        # Whitespace-normalised, and the markdown emphasis stripped. The
        # source is a YAML block scalar, so where a phrase wraps is a
        # consequence of the column it started in -- an assertion that pinned
        # the wrap would fail on a reflow that changed nothing the model sees.
        prompt = " ".join(domain_system_prompt(resolve_domain(RESEARCH_CORPUS)).split())
        prompt = prompt.replace("**", "")

        assert "not a closed list" in prompt
        assert "name the relationship yourself" in prompt
        assert "Relate any kind of entity to any other kind" in prompt

    def test_the_rendered_prompt_carries_no_endpoint_clause(self):
        """The assertion that would catch redstring changing how it renders a
        constraint, which the two above cannot see: they read the schema
        object, and the model reads this string."""
        prompt = domain_system_prompt(resolve_domain(RESEARCH_CORPUS))

        assert "(from:" not in prompt
        assert "to: work)" not in prompt

    def test_extraction_is_not_constrained_to_the_declared_vocabulary(self):
        """`constrain_to_domain` turns the type list into a decoding-time
        `Literal`, at which point every free-form name this change invites
        becomes undecodable and the model returns the nearest listed one
        instead.

        Nothing here sets it and redstring's default is `False`, so this test
        passes today for a reason unrelated to the argument -- it is here to
        fail loudly on the day someone reaches for consistency without
        noticing that the schema has been deliberately opened.
        """
        source = (
            Path(__file__).parents[2]
            / "research_team"
            / "infrastructure"
            / "knowledge"
            / "redstring_adapter.py"
        ).read_text()

        assert "constrain_to_domain" not in source
