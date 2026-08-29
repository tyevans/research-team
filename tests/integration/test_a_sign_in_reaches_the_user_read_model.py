"""A sign-in reaching the `users` table, over a composed application.

Written to CLAUDE.md's "Events" rule and to the shape it names. The recorder,
the projection and the read model are each tested-adjacent elsewhere; none of
those tests can see `UserRunner` go missing from `composition.py`, because
`eventsource` counts an event no projection handles as APPLIED rather than
rejected. In that build the callback still appends, still mints a session
cookie, and still signs the person in -- and `/api/me` reports a stranger,
with nothing raised and nothing logged.

So this asks a *composed* application, and asserts the **row and its values**.
An assertion that `record_sign_in` returned an event, or that nothing threw,
passes identically against a build with the runner unconstructed, which is
precisely the assertion that let the entity-definition gap ship.

The other half this file covers is the one-adapter rule: `EventStoreUserRecorder`
is the only production writer of `UserSignedIn` and `UserProjection` is the
only reader, so a stub on either side would prove the halves work and not that
they meet. Both ends are the real objects here, over a real SQLite log.
"""

import pytest
from eventsource import StreamId
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.user import (
    USER_AGGREGATE_TYPE,
    UserProfileChanged,
    stream_id_for,
)
from research_team.infrastructure.identity.oidc import Claims


@pytest.fixture
async def application(build_application, db_path, fake_model):
    return await build_application(db_path=db_path, model=fake_model)


def _claims(**overrides) -> Claims:
    return Claims(
        **{
            "subject": "zitadel-subject-1",
            "tenant_id": "org-99",
            "email": "ada@example.test",
            "display_name": "Ada Lovelace",
            "avatar_url": "https://pictures.test/ada.png",
            **overrides,
        }
    )


async def test_a_first_sign_in_writes_a_row_with_the_claims_it_carried(application):
    """The row, and every field on it.

    Field by field rather than "a row exists": a projection that wrote a row
    of empty strings would satisfy the weaker assertion, and the whole purpose
    of this table is the values.
    """
    await application.user_recorder.record_sign_in(_claims())
    await application.users.caught_up()

    row = await application.users.get("zitadel-subject-1")

    assert row is not None, (
        "no users row -- the projection is not wired, or is not following the "
        "store the recorder appends to"
    )
    assert row.subject == "zitadel-subject-1"
    assert row.tenant_id == "org-99"
    assert row.email == "ada@example.test"
    assert row.display_name == "Ada Lovelace"
    assert row.avatar_url == "https://pictures.test/ada.png"
    assert row.first_seen_at
    assert row.last_seen_at == row.first_seen_at


async def test_a_second_sign_in_moves_last_seen_and_leaves_created_at(application):
    """`first_seen_at` is "first seen here" and must not follow the clock.

    The two columns are equal after one sign-in -- see the test above -- so a
    build that wrote `first_seen_at` on every sign-in would pass that one
    completely. This is the case that distinguishes them, which is the only
    reason a second sign-in appears in this file at all.
    """
    await application.user_recorder.record_sign_in(_claims())
    await application.users.caught_up()
    first = await application.users.get("zitadel-subject-1")

    await application.user_recorder.record_sign_in(_claims())
    await application.users.caught_up()
    second = await application.users.get("zitadel-subject-1")

    assert second.first_seen_at == first.first_seen_at
    assert second.last_seen_at >= first.last_seen_at


async def test_changed_claims_reach_the_row(application):
    """A rename in the IdP is mirrored on the next sign-in.

    Asserts the *row*, not that a `UserProfileChanged` was appended: an event
    on the log that no projection applied is exactly the failure this file
    exists for, and asserting on the append would be asserting on the half
    that is never in doubt.
    """
    await application.user_recorder.record_sign_in(_claims())
    await application.users.caught_up()

    await application.user_recorder.record_sign_in(
        _claims(display_name="Ada King", email="ada.king@example.test")
    )
    await application.users.caught_up()

    row = await application.users.get("zitadel-subject-1")
    assert row.display_name == "Ada King"
    assert row.email == "ada.king@example.test"


async def test_a_sign_in_with_unchanged_claims_appends_no_profile_change(application, db_path):
    """The event is only written when something actually moved.

    This is the one assertion in the file that is about the *log* rather than
    the row, and it has to be: "only on a real difference" is the entire
    reason `UserProfileChanged` is a separate event, and it is unobservable
    from the read model -- the row is identical either way.
    """

    await application.user_recorder.record_sign_in(_claims())
    await application.user_recorder.record_sign_in(_claims())
    await application.users.caught_up()

    # A second store over the same file, rather than reaching into
    # `Application` for the one it holds: the application exposes no event
    # store, deliberately (nothing outside composition should append through
    # it), and a read-only reader opened on the path is the honest way to ask
    # what is actually on disk. `PositionForeignError` is not a risk here --
    # that is about ordering *positions* across stores, and this reads one
    # stream by id.
    reader = SQLiteEventStore(db_path)
    try:
        stream = StreamId(stream_id_for("zitadel-subject-1"), USER_AGGREGATE_TYPE)
        events = [event async for event in reader.read_stream(stream)]
    finally:
        await reader.close()
    # `read_stream` yields `EventEnvelope`s, so the domain event is
    # `.event` -- an `isinstance(envelope, UserProfileChanged)` check is
    # vacuously false for every envelope and would pass against any log at
    # all, including one holding nothing but profile changes.
    appended = [envelope.event for envelope in events]
    assert [type(event).__name__ for event in appended] == ["UserSignedIn", "UserSignedIn"]
    assert not [event for event in appended if isinstance(event, UserProfileChanged)]


async def test_an_unknown_subject_has_no_row(application):
    """The negative, without which every assertion above would pass against a
    `get` that invented a row for anything it was asked about."""
    assert await application.users.get("nobody-has-ever-signed-in-as-this") is None
