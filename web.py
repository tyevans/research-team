"""Process entrypoint for the web UI: build the application, serve it."""

from contextlib import asynccontextmanager

import uvicorn

from research_team.composition import build_application
from research_team.infrastructure import config
from research_team.interfaces.web import (
    ExtractionActivity,
    TurnActivity,
    WebApprovals,
    create_app,
)


def main() -> None:
    # One object on both sides of the wire: the executor asks it for decisions,
    # the HTTP routes hand it the answers. Built here because it is the seam
    # between them, and the composition root is where seams are chosen.
    approvals = WebApprovals()
    activity = TurnActivity()
    # One instance, both sides, for the same reason `approvals` is one: the
    # `remember` tool reports into it and the roster and the pane read out of
    # it. Two would give the roster and the pane different answers about the
    # same ingest.
    extraction = ExtractionActivity()
    application = build_application(approvals=approvals, extractions=extraction)

    @asynccontextmanager
    async def lifespan(_app):
        # Started and stopped by the server, not here: the `/sessions`
        # projection opens its own database connection, and aiosqlite binds a
        # connection to the loop that created it. Opening it under uvicorn's
        # loop is the whole reason building and starting are separate steps.
        await application.start()
        yield
        await application.close()

    uvicorn.run(
        create_app(
            application.service,
            application.feed,
            application.turns,
            lifespan,
            approvals=approvals,
            activity=activity,
            # Was missing: the source routes have been 503ing in this
            # entrypoint while the test fixture wired a corpus and passed.
            corpus=application.corpus,
            workers=application.workers,
            extraction=extraction,
            topics=application.topic_readers,
            # The same object the executor's gating predicate reads, which is
            # the only reason the routes over it can change anything: a copy
            # would answer reads correctly and change nothing. Instance-wide,
            # so a change made in one browser session applies to all of them --
            # see `set_autonomy` for why that is the trade taken.
            policy=application.policy,
            # Withheld unless this instance was configured for it, so the
            # routes are absent rather than present-and-refusing. See
            # `config.auto_research_over_http`: there is no authentication in
            # front of this port, and this is the one route that would spend
            # an hour of model time for whoever calls it.
            research=application.research if config.auto_research_over_http() else None,
        ),
        host=config.web_host(),
        port=config.web_port(),
    )


if __name__ == "__main__":
    main()
