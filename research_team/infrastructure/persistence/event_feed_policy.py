"""Routing policies and aggregate type classifications for the live event feed.

Defines which aggregate types and stream categories are admitted to the global
SSE event feed (`FEED_AGGREGATE_TYPES`), and explicitly catalogues those kept off
the feed (`UNROUTED_AGGREGATE_TYPES`) along with the architectural rationale for
each decision.
"""

from redstring.events.streams import CONSOLIDATION_CATEGORY, DOCUMENT_CATEGORY

from research_team.curriculum.domain.authoring_run import (
    COURSE_AUTHORING_RUN_AGGREGATE_TYPE,
)
from research_team.curriculum.domain.course import Course
from research_team.curriculum.domain.curation import CATALOG_AGGREGATE_TYPE
from research_team.curriculum.domain.learner import LearnerProgress
from research_team.dialogue.domain.ask import AskConversation
from research_team.dialogue.domain.interaction import BROWSER_SESSION_AGGREGATE_TYPE
from research_team.dialogue.domain.socratic import SocraticDialogue
from research_team.knowledge.domain import EntityJudgements
from research_team.knowledge.domain.ontology import ONTOLOGY_AGGREGATE_TYPE
from research_team.research.domain import Corpus
from research_team.research.domain.media_proposals import MediaProposals
from research_team.research.domain.run import ResearchRun
from research_team.research.domain.topic import Topic
from research_team.session.domain import Session
from research_team.tenancy.domain import Project
from research_team.tenancy.domain.tenant import TENANT_AGGREGATE_TYPE
from research_team.tenancy.domain.user import USER_AGGREGATE_TYPE

__all__ = [
    "FEED_AGGREGATE_TYPES",
    "KNOWLEDGE_CATEGORIES",
    "UNROUTED_AGGREGATE_TYPES",
]

KNOWLEDGE_CATEGORIES = (DOCUMENT_CATEGORY, CONSOLIDATION_CATEGORY)
"""redstring's stream categories, as they appear on this store's feed.

Named here rather than at each use because two places have to agree on it and
they are in different layers: `read_since` decides which categories reach the
feed, and `_sse` decides how a frame from one is addressed. Split, a third
category added upstream could be read and then rendered as a session -- which
is a mislabelled frame rather than an absent one, and the harder of the two to
notice.
"""

FEED_AGGREGATE_TYPES = (
    Session.aggregate_type,
    Project.aggregate_type,
    Topic.aggregate_type,
    Corpus.aggregate_type,
    MediaProposals.aggregate_type,
    Course.aggregate_type,
    *KNOWLEDGE_CATEGORIES,
)
"""Every aggregate type `read_since` admits to the live feed.

A module constant rather than a tuple literal inside `read_since` because it
is now read twice: by the query loop, and by
`test_every_aggregate_type_is_routed_or_deliberately_not`, which is the guard
against this list falling behind the domain a fourth time. The guard can only
compare against a list it can see.

Order is presentation, not behaviour -- `read_since` sorts by position after
merging -- so it is written to match the order `_sse` tests the types in.

`MediaProposals` is routed because a proposal's state changes without any
user action in the tab. Accepting one answers 202 immediately, and the
terminal state (`stored` or `failed`) arrives only after a download plus a
perception pass -- minutes, for an hour of audio. A pane that updated only on
reload would show an accepted proposal sitting in a working state forever,
which is precisely the defect BACKLOG.md B94 records for media rows during
transcription. Routing it is what makes the review pane's live state possible
at all.

`Course` is routed for the reason CLAUDE.md's own controller ruling states
(task-8-brief.md: "a person's decision, which is what the feed is for") --
realizing or abandoning a course is a person clicking a button in one tab,
with nothing else on the log covering the same repaint. Unlike
`CourseAuthoringRun` below, no in-memory channel already announces it: an
open catalog page in a second tab would otherwise show a stale card until
reload. This is the opposite call from `CourseAuthoringRunStarted`'s, and
deliberately so -- see that entry in `UNROUTED_AGGREGATE_TYPES` for why an
existing `Authoring` frame makes routing the run itself redundant, which is
not true here.
"""

UNROUTED_AGGREGATE_TYPES = frozenset(
    {
        ResearchRun.aggregate_type,
        LearnerProgress.aggregate_type,
        EntityJudgements.aggregate_type,
        ONTOLOGY_AGGREGATE_TYPE,
        AskConversation.aggregate_type,
        SocraticDialogue.aggregate_type,
        BROWSER_SESSION_AGGREGATE_TYPE,
        COURSE_AUTHORING_RUN_AGGREGATE_TYPE,
        CATALOG_AGGREGATE_TYPE,
        TENANT_AGGREGATE_TYPE,
        USER_AGGREGATE_TYPE,
    }
)
"""Aggregate types deliberately kept off the feed, and the other half of the guard.

Being *absent* from `FEED_AGGREGATE_TYPES` is not a decision anybody wrote
down -- that is exactly how `Topic`, the graph, `Corpus` and `Project` each
went a release with a live path that carried nothing. Listing the exclusions
makes silence impossible: a new aggregate type is in one list or the other,
and the guard fails until somebody says which.

`ResearchRun` is off because the course page reads a run's state through
`/api/projects/{id}/run`, refreshed off the session frames a round already
emits -- its own frames would be a second signal for the same repaint. See
`useTreeRefresh`, which invalidates `allRuns` on log frames.

`LearnerProgress` is off because nothing renders it live: it is read on
opening a lesson and written by the reader who is already looking at it, so a
frame would arrive at the one client that does not need telling.

`EntityJudgements` is off because nothing renders a judgement. The events a
human's decision produces are consumed by consolidation, not by a view, and
what a viewer would actually want to see repaint is the *merge* that follows --
which is redstring's own event on the graph's stream, already routed. This is
the entry to revisit when the aliases panel lands (piece 3 of the entity-
judgements design): a panel listing what you have taught the project is a view
of these events, and then it belongs on the feed.

`Ontology` is off because the ontology view is a page a reader opens
deliberately and which reads its classes on open, not a pane that sits watching.
The pass that writes these events is queued through the same route a human just
pressed, so the one client that would be told is the one already waiting on the
202 it got back. The staleness this leaves is real and bounded: a pass finishing
while the view is open does not repaint it until a refresh. That is the same
trade `extraction_queue.py`'s docstring makes and states -- a frame type, a
pump, a `decodeFrame` case and a store cost more than they buy until somebody
is watching two tabs. Revisit when the ontology view becomes something left
open while a sweep runs across a project's documents, because then the missing
repaint is the whole point of having it open.

`AskConversation` is off for `LearnerProgress`'s exact reason: the asking
client is already receiving its answer through the ask's own stream -- the
generator that yields the turn back to the tab that asked it -- so a feed
frame would arrive at the one client that does not need telling. It costs a
second tab: a history pane open on the same project while another tab is
mid-conversation does not repaint, because nothing on that path reaches
`read_since`. Revisit when a history pane is actually built and is meant to
be left open while another tab asks -- the missing repaint only matters once
something is watching for it, the same condition `Ontology`'s paragraph
above names for its own pane.

`CourseCatalog` -- featuring and unfeaturing a course -- is off for
`AskConversation`'s reason. The only client that would repaint is the catalog
page the curator pressed the button on, and it invalidates its own query on the
202 it got back, so a frame would tell the one client that already knows.

It sits beside `Course` on the feed and is the near-miss worth stating: both
are decisions a person makes on the same page, and `Course` is *on* the feed
because realizing starts a background authoring run whose progress somebody
else may be watching. Featuring changes a rank and finishes. Nothing keeps
running, so nothing else needs telling.

It went unlisted rather than decided when increment 1 shipped, which left
`test_every_aggregate_type_is_routed_or_deliberately_not` red on main from
that merge until now -- the guard did its job and nobody read it.

`SocraticDialogue` is off for `AskConversation`'s reason and one more: the
only client that would repaint on a dialogue frame is the browser already
holding the SSE stream that produced it, so a feed frame would be a second
signal for a repaint that has already happened.

`browser_session` is off for a different reason than the rest of this set:
it is not merely unrendered, it is not reachable here at all. Interaction
events are appended to their own store (`interactions.db`), not this one, so
`read_since` -- which queries *this* store -- never sees them regardless of
this tuple's contents. It is listed anyway so the coverage guard in
`test_feed_coverage.py`, which walks every registered `DomainEvent` subclass
in `research_team.domain` without regard to which store it lives in, has
somewhere to record the decision instead of failing on a type it cannot place.

`CourseAuthoringRun` is off for `ResearchRun`'s reason exactly.
`AuthoringActivity` already publishes an `Authoring` frame per target over its
own listeners, carrying which area is in hand and how many are done -- richer
than anything these events could say, because it knows the target *currently*
being written and the log deliberately does not. Routing these too would put
two accounts of one run on one connection, and the way that goes wrong is a
progress line and a status disagreeing with nothing in either signature to
catch it. Revisit if that in-memory channel is ever retired in favour of the
log, which is the change that would make this the only signal rather than a
second one.

`Tenant` is off, and this is the entry most likely to be read as the wrong
call, so the reasoning is written out rather than compressed. The surface these
events will move is a **member list** -- somebody joins, somebody's role
changes, somebody is removed -- and that is a second person looking at a view
while a first person acts on it, which is the case this feed exists for. On the
question alone, it should be routed.

It is off because *routing it now would not produce that*, which was measured
rather than assumed. There is no `_sse` branch for it and no `tenant_change`
presenter, so a tenant event falls to the generic `feed_event`, which addresses
the frame `session_id: <the tenant's uuid5>` -- a session that does not exist --
and carries `summary: ""`, because `event_summary` has no case for these and
`event_row` reads a fixed set of fields, none of which a tenant event has. The
browser then decodes it as an ordinary log frame and files a blank row against a
session id nothing can place. That is a live path that carries nothing, dressed
as a live path that works, which is the exact defect `FEED_AGGREGATE_TYPES` and
this set were created to stop happening a fifth time.

Routing it properly is three edits this slice must not make: a presenter, an
`_sse` branch in `app.py` -- which W-B's B1 holds at *zero lines* on purpose,
because that file is the contended one and B3 is the slice that opens it -- and
a `decodeFrame` case plus a store in the console, which is B5.

**B5 owns the revisit, and it is not optional there.** Once this type is named
here the coverage guard goes quiet about it forever, which is the standing cost
of every entry in this set; the difference is that the others are waiting on a
pane nobody has scheduled and this one is waiting on a pane that is already
planned. The condition is precise: when the members page lands, this entry moves
to `FEED_AGGREGATE_TYPES` and gets its own frame type, or the page updates only
on reload -- and it will be a second person's browser that is wrong, which is
the reload nobody thinks to press.

Note also what is *not* the reason. An earlier draft of this entry rejected
routing on the grounds that the feed is unfiltered until B6, so an
`InvitationCreated` frame would broadcast an invitation's single-use token to
every connected client. That was checked and is false today: `event_row` dumps
no arbitrary fields, so neither the token nor the email reaches the wire. It
becomes true the moment somebody writes the `tenant_change` presenter, so
whoever does that in B5 must put the payload behind B6's per-connection filter
in the same change -- a frame carrying a credential is a different question from
a frame carrying a repaint, and only one of them is safe to ship early.

`User` is off because the only writer is the OIDC callback, and a callback is
a full-page navigation: the browser that would receive the frame is being
replaced by a page load in the same instant, and every other tab in that
browser is about to see the same person it already saw. `UserSignedIn` is
appended on every sign-in, so routing it would put a frame on the connection
of every open tab each time anybody signs in anywhere -- a repaint per
sign-in, for a display name that has not moved.

It is also off for the second reason `Tenant` above sets out and measured:
there is no `_sse` branch and no presenter for these, so routing one now would
not produce a live view -- it would put a blank row addressed to a session id
that does not exist into every connected browser. That measurement was taken
against `Tenant` and applies here unchanged; it is cited rather than re-taken.

The revisit condition is `Tenant`'s members page, not a separate one. A pane
listing who is in a tenant renders a *person* -- a name, an avatar -- so the
change that gives `Tenant` a presenter and a `decodeFrame` case is the change
that should ask whether a `UserProfileChanged` belongs on the same frame. Until
then, moving this type alone would buy a repaint of nothing.

The staleness this leaves, stated because it is real: a display name changed
in Zitadel while a tab is open does not reach that tab's account menu until a
reload. Nothing decides anything on a display name, so the cost is cosmetic
and bounded by one page load.

None of the others is a *correctness* argument, and if any grows a pane the
answer is to move it into `FEED_AGGREGATE_TYPES` and give `_sse` a branch --
not to widen this set.
"""
