"""Turn-level spans.

`eventsource` already traces its own store and repository calls, but those are
the leaves. Without a span around the turn that caused them, a trace is a pile
of appends with nothing saying which turn they belonged to or how much of the
elapsed time was the model rather than the database -- which is the actual
question anyone opens a trace to answer.
"""

from eventsource.observability import MockTracer


async def test_a_turn_opens_a_span(build_application, fake_model):
    tracer = MockTracer()
    application = await build_application(model=fake_model, tracer=tracer)
    session_id = await application.service.create_session()

    await application.service.run_turn(session_id, "hello")

    assert "research_team.turn" in tracer.span_names


async def test_a_failing_turn_still_closes_its_span(build_application, fake_model):
    """A span that only ends on success reports failures as infinite duration."""
    tracer = MockTracer()
    application = await build_application(model=fake_model, tracer=tracer)
    session_id = await application.service.create_session()
    fake_model.responses = []  # nothing to reply with

    with __import__("contextlib").suppress(Exception):
        await application.service.run_turn(session_id, "this will not work")

    assert "research_team.turn" in tracer.span_names


async def test_tracing_is_off_unless_asked_for(build_application, fake_model):
    """The default costs nothing.

    This is a local tool, not a service with a collector waiting for it. An
    application built without a tracer gets the library's no-op one, so the
    spans are constructed and discarded rather than exported.
    """
    application = await build_application(model=fake_model)

    assert application.service.tracer.enabled is False
