"""Discovery, over an application the composition root actually built.

Every other test of this feature builds its collaborators by hand: the
application suite fakes all three ports, and the read-model suite drives the
projection through a runner it constructed itself. Both stay green in a build
where `composition.py` never constructs an `OntologyRunner` at all -- the
discovery service would append its event, nothing would be subscribed to it,
and `eventsource` counts an event no projection handles as APPLIED rather than
rejected. Nothing raises, nothing logs, and every class request answers with an
empty list.

That is the exact shape the entity-definitions work shipped once and this file
exists to catch. It can only be caught by asking a composed application, and
only by asserting a *row* -- an assertion that the pass "succeeded" passes
perfectly against a build with no projection wired.

**It has already earned that twice, and both defects were invisible to the unit
suite for the same reason.** The recorder appended without publishing, so no
projection ever saw the event; and `OntologyRunner.caught_up` compared against
the store's global end, which it could never reach. Every unit test missed both
because each builds its own store holding only the events it appended, and each
publishes by hand -- so neither the delivery path nor the wait had anything to
get wrong. Those are properties of a *composed* system, and only a composed
system can be asked about them.

**What is still faked, stated rather than implied.** The model is a
`FakeMessagesListChatModel`, so what is proven about `ChatModelOntologyText` is
that composition hands it the model and that its reply reaches
`parse_ontology`, not anything about a real endpoint's output.
"""

import asyncio
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.composition import build_application

SONGS = (
    "There are six difficulties available in the game: EASY, NORMAL, HARD, "
    "EXPERT, MASTER, and APPEND."
)

FOUND = AIMessage(
    content=(
        '{"classes": [{"name": "Difficulty", "kind": "ordered_scale", '
        '"declared_count": 6, "evidence": {"start": 0, "end": 66}, '
        '"members": [{"name": "EASY", "ordinal": 0}, {"name": "MASTER", "ordinal": 4}]}]}'
    )
)


@pytest.fixture
async def composed(db_path):
    """A started application and one project holding the songs document."""
    application = build_application(
        model=FakeMessagesListChatModel(responses=[FOUND, FOUND]), db_path=db_path
    )
    await application.start()
    project_id = uuid4()
    yield application, project_id
    await application.close()


async def _store(application, project_id, source_id, text):
    """Put a document in a project's corpus through the composed editor.

    `application.editor`, not a hand-built repository: the point of this file
    is that everything it touches came out of `build_application`, and a
    document written around the composition root would prove less than it
    looks like it proves.
    """
    await application.editor.store(project_id, source_id, text)
    # Waits for the *row*, not for a global log position. `CorpusRunner`
    # subscribes to `Corpus` alone, and storing a document also appends
    # redstring's `DocumentChunked` on another stream -- so `caught_up`, which
    # compares against the store's global end, can never reach it and runs its
    # full timeout. `SessionSummaryRunner.caught_up` documents that trap at
    # length; this is the same one from the other side.
    for _ in range(500):
        if await application.corpus.get(project_id, source_id) is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{source_id} never reached the corpus table")


async def test_a_composed_app_discovers_and_stores_a_class(composed):
    """The claim the whole feature can ship without.

    Asserts the stored row, not that `discover` returned a number: a build
    with `OntologyRunner` unconstructed appends the event, subscribes nothing,
    and returns 1 from `discover` exactly as a correct build does. Only the row
    tells them apart.
    """
    application, project_id = composed
    await _store(application, project_id, "songs", SONGS)

    found = await application.ontology_discoverers(project_id).discover("songs")
    assert found == 1
    await application.ontology.caught_up()

    (row,) = await application.ontology.classes_for(project_id)
    assert row.name == "Difficulty"
    assert row.kind == "ordered_scale"
    assert (row.declared_count, row.member_count) == (6, 2)
    assert [m.member_name for m in await application.ontology.members_for(row.id)] == [
        "EASY",
        "MASTER",
    ]


async def test_each_project_is_discovered_from_its_own_corpus(composed, db_path):
    """The recorder and the corpus reader each bind a project at construction,
    so a factory that handed every project one shared service would pass the
    test above and fail this one. Nothing single-project can see it, which is
    why a second project is made here."""
    application, project_id = composed
    other_project_id = uuid4()
    await _store(application, project_id, "songs", SONGS)
    await _store(application, other_project_id, "songs", SONGS)

    await application.ontology_discoverers(project_id).discover("songs")
    await application.ontology.caught_up()

    assert len(await application.ontology.classes_for(project_id)) == 1
    # The other project has the same document and has not been passed over.
    assert await application.ontology.classes_for(other_project_id) == []


async def test_the_sweep_lists_a_document_until_a_pass_has_examined_it(composed):
    """`ungrouped` takes the examined set as an argument, so this is the join
    the route makes, exercised end to end: extracted-but-unexamined in, nothing
    out once the pass has run."""
    application, project_id = composed
    await _store(application, project_id, "songs", SONGS)

    examined = await application.ontology.sources_with_classes(project_id)
    assert examined == set()

    await application.ontology_discoverers(project_id).discover("songs")
    await application.ontology.caught_up()

    assert await application.ontology.sources_with_classes(project_id) == {"songs"}
