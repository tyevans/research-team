"""The in-flight buffer that lets a browser catch up on extraction progress."""

from uuid import uuid4

from research_team.application.knowledge import ExtractionNote
from research_team.interfaces.web.extraction import EXTRACTION, ExtractionActivity


def note(**over) -> ExtractionNote:
    return ExtractionNote(**{"source_id": "notes", "stage": "extracting", **over})


def test_a_reporter_broadcasts_to_every_listener():
    activity = ExtractionActivity()
    project_id = uuid4()
    one, two = activity.listen(), activity.listen()

    activity.reporter(project_id)(note())

    for queue in (one, two):
        frame = queue.get_nowait()
        assert frame["type"] == EXTRACTION
        assert frame["project_id"] == str(project_id)
        assert frame["stage"] == "extracting"


def test_in_flight_answers_the_roster_with_the_latest_stage():
    activity = ExtractionActivity()
    project_id = uuid4()
    report = activity.reporter(project_id)

    report(note(stage="storing"))
    report(note(stage="consolidating", index=7, total=23, detail="Roediger"))

    snapshot = activity.in_flight(project_id)
    assert snapshot is not None
    assert snapshot.source_id == "notes"
    assert snapshot.stage == "consolidating"
    assert (snapshot.index, snapshot.total) == (7, 23)
    assert snapshot.detail == "Roediger"


def test_a_finished_extraction_is_no_longer_in_flight_but_is_still_readable():
    """The catch-up route must be able to show the last one.

    A pane that emptied the moment an extraction finished would throw away
    the only summary of what just happened.
    """
    activity = ExtractionActivity()
    project_id = uuid4()
    report = activity.reporter(project_id)

    report(note(stage="extracting"))
    report(note(stage="consolidated", entities=2, relationships=1))

    assert activity.in_flight(project_id) is None
    assert activity.current(project_id) == []
    last = activity.last(project_id)
    assert last and last[-1]["stage"] == "consolidated"


def test_a_failed_extraction_is_kept_rather_than_dropped():
    """What streamed is the only trace of it that exists.

    Same reasoning as `TurnActivity.discarded`: nothing durable was written,
    so discarding the frames would discard the whole record.
    """
    activity = ExtractionActivity()
    project_id = uuid4()
    report = activity.reporter(project_id)

    report(note(stage="extracting"))
    report(note(stage="failed", detail="the model refused"))

    assert activity.in_flight(project_id) is None
    last = activity.last(project_id)
    assert last and last[-1]["stage"] == "failed"
    assert last[-1]["detail"] == "the model refused"


def test_a_new_extraction_replaces_what_the_last_one_left_running():
    activity = ExtractionActivity()
    project_id = uuid4()
    report = activity.reporter(project_id)

    report(note(source_id="first", stage="extracting"))
    report(note(source_id="second", stage="storing"))

    snapshot = activity.in_flight(project_id)
    assert snapshot is not None and snapshot.source_id == "second"
    assert [frame["source_id"] for frame in activity.current(project_id)] == ["second"]


def test_projects_do_not_see_each_other():
    activity = ExtractionActivity()
    mine, theirs = uuid4(), uuid4()

    activity.reporter(mine)(note())

    assert activity.in_flight(mine) is not None
    assert activity.in_flight(theirs) is None


def test_a_listener_that_has_stopped_gets_nothing_more():
    activity = ExtractionActivity()
    project_id = uuid4()
    queue = activity.listen()
    activity.stop_listening(queue)

    activity.reporter(project_id)(note())

    assert queue.empty()
