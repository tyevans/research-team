"""Process entrypoint for the web UI: build the application, serve it."""

from contextlib import asynccontextmanager

import uvicorn

from research_team.application.curriculum import CurriculumService
from research_team.application.grants import GrantRegistry
from research_team.composition import build_application
from research_team.infrastructure import config
from research_team.interfaces.web import (
    ExtractionActivity,
    TurnActivity,
    WebApprovals,
    create_app,
)
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.extraction_queue import ExtractionQueue
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
    # Web-layer state again, and the thinnest of these channels: it serialises
    # extractions and answers one catch-up route, and publishes nothing --
    # `extraction` above already carries the running one's progress. See
    # `extraction_queue.py`.
    extract_queue = ExtractionQueue()
    # A cache in front of a pure function, not a read model: built here rather
    # than in the composition root because it composes nothing -- it takes the
    # graph reader and the chunk store the routes already resolve per request.
    # One instance so a projection is computed once per graph rather than once
    # per view.
    curriculum = CurriculumService()
    application = build_application(
        approvals=approvals,
        extractions=extraction,
        dispatches=dispatch,
        grants=grants,
        # Both sides of one channel, like `approvals` above: the supervisor
        # opens and fills this buffer, the catch-up route below reads it.
        activity=activity,
    )

    # Built *after* `build_application`, unlike every other web-layer channel
    # above, because it is no longer only web-layer state: an authoring run's
    # targets and their session ids go on the log, so this needs the
    # application's repository and its projection. The ordering is the whole
    # difference between this and `seeding` beside it.
    authoring = AuthoringActivity(application.authoring_runs, application.authoring)

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
            blob_store=application.blob_store,
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
            curriculum=curriculum,
            course_author=application.course_author,
            reembed=application.reembed,
            authoring=authoring,
            # Three references to fields `Application` does not have yet.
            # Composition wiring for the catalog -- `CatalogService`, the
            # `CatalogFeatureStore` read side, and the recorder factory that
            # appends `CourseFeatured`/`CourseUnfeatured` -- is a separate,
            # later piece of work (registering `CatalogFeatureProjection`
            # with the application's projection set, in particular, has to
            # happen in `composition.py` beside every other projection this
            # process starts, per its own comment on why one forgotten there
            # is a projection nobody starts). Left wired here anyway, rather
            # than omitted or passed as `None`: `test_web_entrypoint.py`
            # checks this call by parsing this file's source, not by
            # importing `Application`, so it demands the parameter be
            # supplied without demanding the attribute already resolve. The
            # alternative -- leaving these three out until that later change
            # lands -- is exactly the gap `topic_repository` and `corpus`
            # shipped through three times before this test existed: routes
            # added to `create_app` and not to this call answer 503 in the
            # running server while every test that builds its own app passes.
            catalog=application.catalog,
            # A getter, not the attribute: `catalog_features` is `None` until
            # the lifespan above has run `start()`, and this call happens
            # first. Reading it here captured that `None` and every catalog
            # request in this entrypoint answered 503 while all three catalog
            # test files passed -- they start the application before building
            # the app, which is an ordering the server cannot use.
            catalog_features=lambda: application.catalog_features,
            catalog_recorder=application.catalog_recorder,
            dispatcher=application.dispatcher,
            dispatch=dispatch,
            ask=application.ask,
            # The read side of the same feature: `ask` appends a conversation
            # and this is what the history routes read it back through. The
            # started runner from the application, never a second one built
            # here -- a second instance would open its own connection to the
            # same tables and answer from whatever the projection it is not
            # following had got to.
            asks=application.asks,
            # The read side of socratic dialogues, and the same argument as
            # `asks` above: the started runner from the application, never a
            # second one built here. It is also what the dialogue *service*
            # resumes through, so a build that passed a second instance would
            # answer history from a projection nothing is following.
            dialogues=application.dialogues,
            # The write side of dialogues, beside the read side above. `ask`
            # has the same shape and the same history: routes added to
            # `create_app` and not to this call have shipped 503ing three times
            # while every test built its own app and passed.
            # `test_web_entrypoint.py` exists for that and is what went red
            # when this parameter was added.
            socratic=application.socratic,
            extractor=application.document_extractor,
            extract_queue=extract_queue,
            # The write side beside the read side above: without it every
            # upload/edit/drop/restore route in this entrypoint 503s while
            # `app_and_client` in the tests wires one and passes -- the same
            # gap `corpus` and `topic_repository` closed above it.
            editor=application.editor,
            # Both halves of perception, and both from the application rather
            # than built here: `perceiver` holds the corpus repository the
            # editor holds, and `perception` is the very port it perceives
            # through -- a second adapter built at this call site would answer
            # the route's capability check from a different reading of the
            # environment than the job's.
            perception=application.perception,
            perceiver=application.perceiver,
            # The factory, not a service: one per project, built on demand.
            # This is the instance whose cache is the same table
            # `application.definitions` marks stale, which is the only reason
            # a definition invalidated by an extraction is regenerated rather
            # than served from a second connection that never heard about it.
            definitions=application.definition_readers,
            # Both halves of the ontology layer. The runner is the read side --
            # the tables the projection writes -- and the factory is the write
            # side, one service per project. Passing only one of them leaves a
            # route answering 503 in the build that ships, which is the failure
            # `definitions` above was one review away from.
            ontology=application.ontology,
            ontology_discoverers=application.ontology_discoverers,
            # The read side (the runner, started like every other projection)
            # and the write side (the repository `MediaCurationService` and
            # the accept/reject/ignore routes both append through) -- missing
            # either would 503 half of `/media-proposals`, the same gap
            # `ontology`/`ontology_discoverers` above close for that pair.
            media_proposals=application.media_proposals,
            media_proposal_repository=application.media_proposal_repository,
            # The worker the accept route (above) hands off to -- Task 11b.
            # Without this, accepting a proposal here still appends the event
            # and answers 202, but nothing ever downloads or stores it: the
            # same gap the two comments above this one close for ontology and
            # media-proposals, one route further down the same lifecycle.
            media_accept_worker=application.media_accept_worker,
            # `None`/`None` together when this install has no SearXNG
            # instance -- see `media_curation_text`'s docstring in
            # `composition.py`. Passed through rather than rebuilt here so
            # this entrypoint runs the chain over the exact model and search
            # client `config` resolved, not a second reading of it.
            curation_text=application.media_curation_text,
            curation_search=application.media_curation_search,
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
            # Unlike every other flag-gated dependency above, this one
            # defaults to on: `config.interaction_log_enabled` argues that
            # "unset means the route is not there" is the stronger promise
            # for an optional capability, but a log nobody collects is worth
            # nothing, so interaction telemetry ships collecting unless
            # someone opts out.
            interactions=(
                application.interaction_recorder if config.interaction_log_enabled() else None
            ),
            # A getter, not `application.interaction_log.reader`, and not
            # gated on the flag above. `InteractionLogRunner.reader` raises
            # until `start()` has run, and `start()` runs in the lifespan --
            # after this call. Reading the attribute here would raise at
            # wiring time and the server would not come up at all, which is
            # `catalog_features`'s bug one degree worse. The lambda is only
            # ever called from inside a request, by which point the lifespan
            # has run.
            #
            # Ungated on purpose: `AGENT_INTERACTION_LOG=0` stops the
            # *recorder*, and the explorer's whole job is to say so -- 200
            # with an empty log and `collecting: false`, rather than a 503
            # that reads identically to a broken instrument.
            interaction_reader=lambda: application.interaction_log.reader,
            # Bound method rather than the runner: the health route needs the
            # dead letters and none of the lifecycle beside them.
            interaction_failures=application.interaction_log.failures,
            # The write side of Task 9's routes: `course_repository` is what
            # `RealizeCourse`/`AbandonCourse` execute against, `course_service`
            # is what the detail route reads through, and `blurb_sweep`/
            # `blurbs` are the sweep button and the writer it hands off to.
            # Following `catalog`'s own precedent above rather than
            # `catalog_features`'s: none of the four is `None` until `start()`
            # runs -- they are built in `build_application` itself, not
            # assigned by a projection's subscription -- so there is no stale
            # `None` for this call to capture.
            course_service=application.course_service,
            course_repository=application.course_repository,
            blurb_sweep=application.blurb_sweep,
            blurb_writer=application.blurbs,
            outline_writer=application.outlines,
            art_store=application.art_store,
            art_sweep=application.art_sweep,
            art_reroll=application.art_reroll,
            art_generator=application.art_generator,
            art_matcher=application.art_matcher,
        ),
        host=config.web_host(),
        port=config.web_port(),
    )


if __name__ == "__main__":
    main()
