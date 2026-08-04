"""Tracing setup: off by default, and free when it is off.

This is a local tool, not a service with a collector waiting for it, so the
default has to cost nothing. `eventsource` is built for that -- its `Tracer`
is a no-op unless OpenTelemetry is installed *and* tracing is asked for, and
every span in the library and in this codebase is written unconditionally
against that interface. Turning tracing on is therefore a deployment decision
made here, not a set of `if` statements scattered through the code.

To actually export anything you need the optional dependencies:

    uv sync --extra tracing

and then `AGENT_TRACING=1`, plus `AGENT_OTLP_ENDPOINT` if the collector is not
at the default. Without the extra, setting the variable is harmless: there is
nothing to configure, so it stays a no-op and says so in the log.
"""

import logging

from eventsource.observability import Tracer, create_tracer

from research_team.infrastructure import config

logger = logging.getLogger(__name__)

_configured = False


def build_tracer() -> Tracer:
    """A tracer for this process: real if configured, no-op otherwise."""
    if not config.tracing_enabled():
        return create_tracer(__name__, False)
    _configure_provider_once()
    tracer = create_tracer(__name__, True)
    if not tracer.enabled:
        logger.warning(
            "AGENT_TRACING is set but OpenTelemetry is not installed; "
            "spans will be discarded. Install the extra with: uv sync --extra tracing"
        )
    return tracer


def _configure_provider_once() -> None:
    """Install a tracer provider and an OTLP exporter, at most once.

    Guarded because a process may build more than one application -- tests do,
    and so does anything serving multiple databases -- and installing a second
    provider would either be ignored or duplicate every span.
    """
    global _configured
    if _configured:
        return
    _configured = True
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        # Reported by the caller, which knows whether the user asked for this.
        return

    provider = TracerProvider(
        resource=Resource.create({"service.name": config.tracing_service_name()})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=config.otlp_endpoint()))
    )
    trace.set_tracer_provider(provider)
    logger.info("tracing enabled, exporting to %s", config.otlp_endpoint())
