"""What the identity provider told us about a person, on the log.

The system of record for *who somebody is* is Zitadel, not this log. That is
the whole point of putting an OIDC provider in front: password hashes, MFA
enrolment, email verification and the rest are somebody else's problem, and
duplicating them here would mean two answers to "is this address confirmed"
that could disagree.

So these two events are not a `User` aggregate in the usual sense. They record
*observations* -- "at this moment the IdP said this subject has this email and
this name" -- and the read model beside them is a mirror kept current enough to
render an avatar and a display name without a network hop on every request.
Everything authoritative stays upstream.

Appended directly rather than through a `DeciderAggregate`, following
`catalog_curation.py` and `ontology.py`: there is no invariant here for a
decider to protect. A person cannot sign in "twice invalidly", and a profile
change is whatever the IdP now says it is -- refusing one would mean this log
arguing with the system of record.

**Why two events rather than one `UserObserved`.** They answer different
questions and only one of them is interesting in quantity. `UserSignedIn` is
an activity signal: it is appended on *every* sign-in, and a count of them per
subject is the "last seen" the read model carries. `UserProfileChanged` is
appended only when a claim actually differs from what the mirror already
holds, so its presence on the log always means something moved. Folding them
together would make "how often does this person use the system" and "how often
does this person rename themselves" the same number, and the second is
answerable no other way.

What that costs, stated because it is a real cost: a busy instance writes one
event per sign-in per person forever, and nothing prunes them. The events are
small (five short strings) and sign-ins are human-paced, so this is a slow
leak rather than a fast one -- but it is a leak, and the honest fix when it
matters is a retention pass over this aggregate type, not a change to the
shape here. See BACKLOG when that day arrives.
"""

from uuid import UUID, uuid5

from eventsource import DomainEvent, register_event

USER_AGGREGATE_TYPE = "User"
"""The stream these are appended to, named rather than spelled twice.

There is no `User` aggregate class to ask for `aggregate_type` -- see the
module docstring -- so this constant stands in for the class attribute, the
way `CATALOG_AGGREGATE_TYPE` and `ONTOLOGY_AGGREGATE_TYPE` do next door.
"""

USER_NAMESPACE = UUID("6b1f0c7a-2d95-5f43-8e21-0a7c46b9d3f8")
"""The uuid5 namespace turning a Zitadel subject into this log's stream id.

Distinct from every other namespace in the tree for the reason those state:
several tables key on unrelated things that are all just strings by the time
`uuid5` sees them, and two of them colliding on `id` would be a defect nobody
could reproduce.
"""


def stream_id_for(subject: str) -> UUID:
    """The aggregate id for a subject.

    Derived rather than minted, and that is deliberate rather than tidy. A
    minted id would need a lookup table from subject to id, which is a second
    source of truth for the same fact and a race on first sign-in: two
    concurrent callbacks for a person who has never signed in before would
    each find no row and each mint an id. Deriving makes the mapping a pure
    function, so both callbacks compute the same stream and the event store's
    ordering settles the rest.

    It also keeps the subject out of the id's *meaning*: this is a hash, not
    an encoding, so nothing downstream can be tempted to parse a user id back
    into an OIDC subject.
    """
    return uuid5(USER_NAMESPACE, subject)


@register_event
class UserSignedIn(DomainEvent):
    """A person completed an OIDC flow and got a session.

    Carries the whole claim set rather than only the subject, so that the
    read model can be built from this event alone. The alternative -- subject
    here, claims fetched by the projection -- would put a network call to the
    IdP inside a projection replay, which is the one place a network call must
    never be: a rebuild would then depend on the IdP being up and on the
    person still existing there.

    `tenant_id` is the Zitadel organisation id, and it is a `str` rather than
    a `UUID` because Zitadel's org ids are snowflake-shaped decimal strings,
    not UUIDs. W-B owns what a tenant *means*; this field exists now so that
    the tenancy work has something to key on rather than a backfill to run.
    """

    aggregate_type: str = USER_AGGREGATE_TYPE
    subject: str
    tenant_id: str
    email: str = ""
    display_name: str = ""
    avatar_url: str = ""
    signed_in_at: str
    """ISO-8601, from this process's clock rather than from a token claim.

    `iat` would be the IdP's clock, which is the right answer to "when was
    this token issued" and the wrong answer to "when did this instance last
    see this person" -- the two differ by however long a token is reused.
    """


@register_event
class UserProfileChanged(DomainEvent):
    """The IdP's claims for this subject differ from what the mirror holds.

    Appended only on an actual difference -- see the module docstring on why
    that is what makes this event worth having. The comparison is made against
    the *read model*, not against the previous event, because the read model is
    what the difference would be visible in; comparing against the log would
    mean folding the stream on every sign-in to answer a question a single row
    already answers.

    The subtle consequence, worth stating because it looks like a bug from the
    log's side: if the read model is rebuilt from an arbitrary checkpoint, a
    profile change that happened before that checkpoint is not on the log
    anywhere the replay reaches, and the mirror will carry the *older* claims
    until the person next signs in -- at which point the difference is noticed
    again and re-appended. Self-healing on the next sign-in, wrong until then,
    and that is the trade for not writing an event per sign-in per claim.
    """

    aggregate_type: str = USER_AGGREGATE_TYPE
    subject: str
    tenant_id: str
    email: str = ""
    display_name: str = ""
    avatar_url: str = ""
    changed_at: str
