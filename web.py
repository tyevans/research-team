"""Process entrypoint for the web UI: build the application, serve it."""

from contextlib import asynccontextmanager

import uvicorn

from research_team.application.grants import GrantRegistry
from research_team.composition import build_application
from research_team.infrastructure import config
from research_team.interfaces.web import (
    ExtractionActivity,
    TurnActivity,
    WebApprovals,
    create_app,
)
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.seeding import SeedingActivity


def main() -> None:
    # One instance, shared with `build_application` below, for the reason
    # `approvals` is one object on both sides of the wire: `WebApprovals`
    # needs it to tell a run's session from a person's (`is_unattended`), and
    # the executor's gate and the grant-bound `fetch` tool need the very same
    # grant a run registered under. Two registries would mean the gate could
    # let a call through that `WebApprovals` still treats as unattended-but-
    # ungranted, or the reverse -- see `application/grants.py` and
    # `composition.py`'s `resolved_grants`.
    grants = GrantRegistry()
    # One object on both sides of the wire: the executor asks it for decisions,
    # the HTTP routes hand it the answers. Built here because it is the seam
    # between them, and the composition root is where seams are chosen.
    approvals = WebApprovals(grants=grants)
    activity = TurnActivity()
    # One instance, both sides, for the same reason `approvals` is one: the
    # `remember` tool reports into it and the roster and the pane read out of
    # it. Two would give the roster and the pane different answers about the
    # same ingest.
    extraction = ExtractionActivity()
    # Web-layer state, matching `extraction`: nothing durable backs a seeding
    # run's status, so this buffer is what a reconnecting tab catches up from.
    seeding = SeedingActivity()
    # Web-layer state again, and for once genuinely both halves of one channel:
    # the routes enqueue into this and the roster reads what is running out of
    # it. One object, following `ExtractionChannel`'s reasoning -- two would
    # show a roster that disagreed with the topic rows beside it, and nothing
    # in either signature would catch it.
    dispatch = DispatchQueue()
    application = build_application(
        approvals=approvals,
        extractions=extraction,
        dispatches=dispatch,
        grants=grants,
        # Both sides of one channel, like `approvals` above: the supervisor
        # opens and fills this buffer, the catch-up route below reads it.
        activity=activity,
    )

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
            # The write half of the same pair: `topics` answers the reads and
            # this answers the Manage dialog's writes. Missing here until now,
            # so those routes 503'd in this entrypoint while every test built
            # its own app and passed both -- the third instance of that, which
            # is why `tests/interfaces/test_web_entrypoint.py` now exists.
            # Deliberately the one instance the readers and `research` already
            # close over, not a second built here; see `Application`.
            topic_repository=application.topic_repository,
            graphs=application.graphs,
            topic_seeder=application.topic_seeder,
            seeding=seeding,
            dispatcher=application.dispatcher,
            dispatch=dispatch,
            # The same object the executor's gating predicate reads, which is
            # the only reason the routes over it can change anything: a copy
            # would answer reads correctly and change nothing. Instance-wide,
            # so a change made in one browser session applies to all of them --
            # see `set_autonomy` for why that is the trade taken.
            policy=application.policy,
            # Withheld unless this instance was configured for it, so the
            # routes are absent rather than present-and-refusing. See
            # `config.research_run_over_http`: there is no authentication in
            # front of this port, and this is the one route that would spend
            # an hour of model time for whoever calls it.
            research=application.research if config.research_run_over_http() else None,
        ),
        host=config.web_host(),
        port=config.web_port(),
    )


if __name__ == "__main__":
    main()
