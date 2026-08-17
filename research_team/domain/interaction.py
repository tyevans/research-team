"""What the user did in the console, as events in their own store.

**These payloads carry no evolution contract, and that is the point.**
`domain/events.py` opens with a promise that events already written stay
readable, because that log is the domain's history and is never rewritten.
This log is not history. It is observation: high-volume, derived from a UI
that will be rewritten, and droppable without degrading a single feature.

So when a field here changes shape, the recovery is:

    rm ~/.research-team/interactions.db

Nothing reads an old payload, nothing migrates, and no
`test_schema_evolution.py` case guards these. Do not add one -- a contract
here would buy nothing and cost every future vocabulary change.

The stream is a browser session, and `aggregate_id` *is* the browser session
id. There is deliberately no separate `browser_session_id` field: the stored
`aggregate_id` column comes from the `StreamId` while the payload comes from
the event, so two fields that must agree are two fields that will eventually
disagree without saying so.

There is no aggregate. Nothing here enforces an invariant -- the browser
reports what happened and the server records it -- so events go straight to
the store with `ExpectedVersion.any_()`, the way
`infrastructure/knowledge/ontology_recorder.py` does. The consequence is that
publishing is this feature's own job; see that module's docstring for what
forgetting it looks like.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from eventsource import DomainEvent, register_event
from pydantic import Field

BROWSER_SESSION_AGGREGATE_TYPE = "browser_session"
"""The stream every interaction event is appended to, named rather than
spelled at each site.

There is no `BrowserSession` aggregate to take the name from -- deliberately,
since nothing invariant is being protected -- so the constant stands in for
what would otherwise be a class attribute, and the `StreamId` category cannot
drift from the events' own default.
"""


class InteractionEvent(DomainEvent):
    """The envelope every interaction event carries.

    Not registered: it is never appended on its own. Subclasses are.
    """

    aggregate_type: str = BROWSER_SESSION_AGGREGATE_TYPE

    install_id: UUID
    """Persisted in the browser, surviving restarts, so a count can say "on
    nine separate days" rather than "in nine separate tabs".

    Pseudonymous, and the exact thing that becomes real identity if this
    product ever grows past one user. Named here so that growth is a decision
    rather than an accident.
    """

    seq: int
    """The ordering authority, monotonic within one browser session.

    Not `occurred_at`, which comes from a clock that can be skewed or moved
    mid-session, and not arrival order, which batching makes meaningless. A
    counter survives both.
    """

    view: str
    """Where the user was: a route name, or `project/<facet>` for the facets
    the project page switches between."""

    project_id: UUID | None = None
    session_id: UUID | None = None
    """What the interaction was about, where anything was. Optional because
    plenty of interaction happens with no project in scope."""

    received_at: datetime | None = None
    """When the server took delivery, set at ingest.

    Kept as a cross-check rather than as truth: a batch whose client clock
    disagrees wildly with its arrival is suspect, and that is worth being able
    to notice. Typed loosely because it is set by the edge, never by a caller.
    """


@register_event
class ViewEntered(InteractionEvent):
    """A view became current."""

    params: dict[str, Any] = Field(default_factory=dict)
    """Ids only -- which entity, which topic. Never free text."""


@register_event
class ViewExited(InteractionEvent):
    """A view stopped being current, and for how long it had been.

    Emitted on route change and on the page-hide flush, so a session that ends
    by closing the tab still gets a terminal dwell. Without that, every
    session's last view has no duration -- which is the view where friction is
    most likely.
    """

    dwell_ms: int
    """Wall time in view, from `performance.now()` rather than a wall clock:
    monotonic, so a system clock change cannot produce a negative duration."""

    hidden_ms: int = 0
    """How much of `dwell_ms` the tab was backgrounded for.

    Reported alongside rather than subtracted so the consumer chooses. Without
    it, "stalled on this view for four minutes" -- the archetypal friction
    signal -- is indistinguishable from "went to lunch", and the whole
    attention half of this log is worthless.
    """


@register_event
class AttentionLost(InteractionEvent):
    """The tab was backgrounded."""


@register_event
class AttentionRegained(InteractionEvent):
    """The tab came back."""


@register_event
class EntityOpened(InteractionEvent):
    entity_id: str
    source: str
    """How they got there: graph | search | timeline | link. The same entity
    reached three ways is three different stories about the UI."""


@register_event
class ProjectSwitched(InteractionEvent):
    to_project_id: UUID
    from_project_id: UUID | None = None


@register_event
class ExtractionQueued(InteractionEvent):
    source_id: str


@register_event
class ExtractionCancelled(InteractionEvent):
    source_id: str


@register_event
class DispatchRequested(InteractionEvent):
    topic_id: UUID
    action: str


@register_event
class SearchPerformed(InteractionEvent):
    query_text: str
    """On the content allowlist. The strongest friction signal is "nearly the
    same search again, slightly differently", and a length cannot express
    nearly-the-same."""

    result_count: int


@register_event
class AskSubmitted(InteractionEvent):
    query_text: str
    """On the content allowlist, and the most sensitive field in this system:
    a research prompt is a transcript of what someone was thinking about.

    Included for the same near-duplicate reason as `SearchPerformed`, and the
    cost is real rather than theoretical. `AGENT_INTERACTION_LOG=0` is the
    answer, and it is one variable.
    """


@register_event
class ApprovalDecided(InteractionEvent):
    """A gated tool call was decided, and how the deciding went.

    Deliberately duplicates nothing from the domain's `ToolCallDecided`, which
    already records what was decided. What this adds is UI-only and is the
    distinction `docs/direction.md` §3 turns on: a decision in 400ms without
    opening the details is click-through, and a decision after twelve seconds
    with them open is deliberation. Counting approvals without it produces a
    confident and misleading signal.
    """

    decision: str
    latency_ms: int
    expanded_details: bool
    review_id: UUID | None = None


@register_event
class ActionUndone(InteractionEvent):
    """Repair, and per §3 the strong signal -- given its own kind so it is
    never inferred from a pair of other events."""

    action_kind: str
    target_id: str | None = None


@register_event
class ActionRetried(InteractionEvent):
    action_kind: str
    attempt_number: int


@register_event
class EmptyResultEncountered(InteractionEvent):
    """Somewhere the product had nothing to show. Structural on purpose: the
    count and the place are the signal, and `SearchPerformed` already carries
    the text where text is warranted."""

    where: str
    query_length: int = 0


INTERACTION_EVENTS: tuple[type[InteractionEvent], ...] = (
    ViewEntered,
    ViewExited,
    AttentionLost,
    AttentionRegained,
    EntityOpened,
    ProjectSwitched,
    ExtractionQueued,
    ExtractionCancelled,
    DispatchRequested,
    SearchPerformed,
    AskSubmitted,
    ApprovalDecided,
    ActionUndone,
    ActionRetried,
    EmptyResultEncountered,
)
"""Every kind, in one tuple.

The ingest decoder and the projection both enumerate the vocabulary, and a
kind added to the module but not to this tuple is a kind the route rejects and
nothing records -- with no error naming the omission.
"""

TEXT_BEARING_FIELDS: dict[str, tuple[str, ...]] = {
    "SearchPerformed": ("query_text",),
    "AskSubmitted": ("query_text",),
}
"""The content allowlist, machine-readable and complete.

Everything else in this vocabulary is structure: ids, view names, counts,
durations. Free text is otherwise recorded as shape -- `query_length`,
`result_count` -- which is enough to find a zero-result search without knowing
what was searched.

Machine-readable rather than prose so a test can pin it. Widening it is a
deliberate change with a reason attached, not a judgement call at a call site.
"""
