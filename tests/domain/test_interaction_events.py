"""What the interaction vocabulary promises.

These are cheap tests over declarations, and they exist because the three
things they check are the three that break silently: an event whose
aggregate_type drifts from the constant lands in a stream nothing projects, a
kind missing from INTERACTION_EVENTS is accepted by no decoder, and a text
field absent from the allowlist is content nobody audited.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import DomainEvent

from research_team.domain.interaction import (
    BROWSER_SESSION_AGGREGATE_TYPE,
    INTERACTION_EVENTS,
    TEXT_BEARING_FIELDS,
    AskSubmitted,
    SearchPerformed,
    ViewEntered,
    ViewExited,
)


def _envelope() -> dict:
    return {
        "aggregate_id": uuid4(),
        "install_id": uuid4(),
        "seq": 1,
        "view": "project/entity",
        "occurred_at": datetime.now(UTC),
    }


def test_every_kind_streams_to_the_one_aggregate_type():
    for event_type in INTERACTION_EVENTS:
        assert event_type.model_fields["aggregate_type"].default == (
            BROWSER_SESSION_AGGREGATE_TYPE
        )


def test_every_kind_is_a_domain_event():
    for event_type in INTERACTION_EVENTS:
        assert issubclass(event_type, DomainEvent)


def test_the_allowlist_names_only_fields_that_exist():
    """A stale allowlist entry is worse than none: it claims an audit of a
    field that is not there."""
    by_name = {event_type.__name__: event_type for event_type in INTERACTION_EVENTS}
    for kind, fields in TEXT_BEARING_FIELDS.items():
        assert kind in by_name, f"{kind} is not an interaction event"
        for field in fields:
            assert field in by_name[kind].model_fields


def test_only_search_and_ask_carry_text():
    """The whole content allowlist, pinned. Widening it is a deliberate change
    and this test is where the decision is recorded."""
    assert TEXT_BEARING_FIELDS == {
        "SearchPerformed": ("query_text",),
        "AskSubmitted": ("query_text",),
    }


def test_a_view_entry_carries_where_and_when():
    event = ViewEntered(**_envelope(), params={"entity_id": "ent_4a1f"})

    assert event.aggregate_type == BROWSER_SESSION_AGGREGATE_TYPE
    assert event.view == "project/entity"
    assert event.params["entity_id"] == "ent_4a1f"


def test_a_view_exit_reports_hidden_time_separately_from_dwell():
    """Reported alongside rather than subtracted, so a consumer picks which it
    wants and the raw figures stay inspectable."""
    event = ViewExited(**_envelope(), dwell_ms=240_000, hidden_ms=180_000)

    assert event.dwell_ms == 240_000
    assert event.hidden_ms == 180_000


def test_domain_context_is_optional():
    """Plenty of interaction happens with no project in scope -- the tree view,
    the session list. A required project_id would make those unrecordable."""
    event = ViewEntered(**_envelope(), params={})

    assert event.project_id is None
    assert event.session_id is None


def test_a_search_carries_its_text_and_its_result_count():
    event = SearchPerformed(**_envelope(), query_text="diocletian", result_count=0)

    assert event.query_text == "diocletian"
    assert event.result_count == 0


def test_an_ask_carries_its_prompt():
    """The most sensitive field in the system. Present because near-duplicate
    detection is the strongest friction signal and lengths cannot express it;
    AGENT_INTERACTION_LOG=0 is the answer to it."""
    event = AskSubmitted(**_envelope(), query_text="what did the tetrarchy change")

    assert event.query_text == "what did the tetrarchy change"


def test_seq_is_required():
    """Ordering authority. An event without it cannot be placed, and a default
    would silently place it at zero."""
    envelope = _envelope()
    del envelope["seq"]

    with pytest.raises(ValueError):
        ViewEntered(**envelope, params={})
