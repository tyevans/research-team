"""The wired application: use cases, plus a live view of the same log."""

import asyncio
import logging
import random
from dataclasses import dataclass
from uuid import UUID

from langchain_core.tools import BaseTool

from research_team.infrastructure import config
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence.read_models import (
    CatalogFeatureStore,
    CourseStore,
)
from research_team.wiring.application_state import ApplicationState
from research_team.wiring.lifecycle import _close_every_step

logger = logging.getLogger(__name__)

__all__ = ["Application"]


@dataclass(frozen=True)
class Application(ApplicationState):
    """The wired application: use cases, plus a live view of the same log."""

    @property
    def knowledge(self) -> RedstringKnowledge | None:
        """This instance's currently attached knowledge graph, or None.

        Not a fixed field: which project is attached can change after
        construction, now that a REPL can `/project use` into one. Reads
        through the service, which is what actually owns the attachment --
        so this and `service.current_knowledge` can never disagree.
        """
        return self.service.current_knowledge

    @property
    def catalog_features(self) -> CatalogFeatureStore | None:
        """The read side of course featuring, or `None` until `start()` has
        opened it. `CatalogFeatureStore.open` needs a running event loop --
        the same reason every other projection's store here is opened in
        `start()`, not at construction -- so this reads through
        `_catalog_runner`'s mutable `features` attribute rather than being a
        field of its own; see `_catalog_runner`'s docstring."""
        return self._catalog_runner.features

    async def catalog_caught_up(self) -> None:
        """A test affordance, matching `interaction_log_caught_up` and the rest:
        waits until `catalog_features` has replayed every `CourseFeatured`/
        `CourseUnfeatured` appended so far."""
        await self._catalog_runner.caught_up()

    @property
    def courses(self) -> CourseStore | None:
        """The read side of realized courses, or `None` until `start()` has
        opened it. Mirrors `catalog_features` exactly, and for the same
        reason: `CourseStore.open` needs a running event loop, so this reads
        through `_course_runner`'s mutable `courses` attribute rather than
        being a field of its own; see `_course_runner`'s docstring."""
        return self._course_runner.courses

    async def courses_caught_up(self) -> None:
        """A test affordance, matching `catalog_caught_up`: waits until
        `courses` has replayed every `CourseRealized`/`CourseAbandoned`
        appended so far."""
        await self._course_runner.caught_up()

    async def attach_project(self, project_id: UUID) -> None:
        """Open `project_id`'s graph and give the executor its tools.

        Thin delegation: the service owns the attachment and its atomicity
        guarantee (a failure here must leave `knowledge` at None and the
        executor's tools unchanged), because the REPL calls the same method
        on the service directly -- this exists so the build-time
        `project_id=` path below has one path to go through as well, not two.
        """
        await self.service.attach_project(project_id)

    async def detach_project(self) -> None:
        """Close whatever graph is attached and restore the tools without it."""
        await self.service.detach_project()

    async def start(self) -> None:
        """Open what needs a running event loop to open.

        Building an application is deliberately synchronous -- it picks
        adapters and wires them, nothing more -- because the web entrypoint
        constructs it before uvicorn has a loop, and an aiosqlite connection
        made on one loop cannot be used from another. Anything that has to be
        opened *inside* the loop that will use it is opened here, including
        attaching `_initial_project_id`, if `build_application` was given one
        -- so an unreachable Neo4j fails here, at start, rather than mid-turn.
        """
        await self.summaries.start()
        await self.corpus.start()
        await self.topics.start()
        await self.definitions.start()
        await self.ontology.start()
        await self._catalog_runner.start()
        await self._course_runner.start()
        await self.media_proposals.start()
        # Reconcile proposals a crash left `accepted` -- designed in
        # `docs/superpowers/specs/2026-08-16-accept-reconciliation-design.md`.
        # Here rather than in `web.py`'s lifespan, which is the spec's central
        # ruling: `web.py` carries three "was missing -- these routes have been
        # 503ing in this entrypoint while the test fixture wired one and
        # passed" comments, and a reconciliation that never ran looks exactly
        # like one that found nothing to do, so it must not depend on a call
        # site anyone can forget.
        #
        # After `caught_up()`, not merely `start()`: a projection mid-replay
        # under-reports the accepted set and there is no second pass. The cost
        # is that startup waits for a catch-up it would need before serving
        # anything about proposals anyway.
        #
        # Scheduled, not awaited: an abandoned download is a download, and
        # re-fetching an hour of video must not hold the port closed.
        await self.media_proposals.caught_up()
        self._reconciliation.append(asyncio.create_task(self.media_accept_reconciler.run()))
        # And again, on a timer, for the case the startup pass cannot reach:
        # `BACKLOG.md` B99, now closed -- the design is in the spec named
        # above, under "What this does not do". The pass above fixes a
        # process that died and came back; it does nothing for a process
        # that never dies, where an
        # accept's `asyncio.create_task` raised, hung, or was dropped and the
        # proposal stays `accepted` for as long as the process stays up.
        #
        # Created after `caught_up()` for the same reason the pass above is,
        # and `tests/integration/test_accept_reconciliation.py::
        # test_the_reconciler_reads_only_after_caught_up_returns` is what
        # fails if either line moves above it: the sweep's first read must not
        # land on a projection still mid-replay either.
        self._sweep.append(asyncio.create_task(self._sweep_reconciliation()))
        await self.asks.start()
        await self.authoring.start()
        await self.dialogues.start()
        # Started with the rest rather than lazily on first sign-in: a
        # projection that only starts when somebody logs in is a projection
        # whose absence is invisible on every instance where nobody has yet.
        # It is also the quietest of these to have missing -- the callback
        # still appends, still sets a cookie, and still signs the person in;
        # only `/api/me` comes back describing a stranger. Started
        # unconditionally even with `AGENT_AUTH=off`, so that turning the flag
        # on does not need a restart to have a read model behind it, and so
        # that the two states of the flag differ in one place only.
        await self.users.start()
        await self.interaction_log.start()
        await self.tenants.start()
        if not config.authorization_enabled():
            # `LOCAL_TENANT` is a real tenant with a real row, not a special
            # case in the checker -- see `seed_local_tenant`. Only with auth
            # off: with it on, a `"local"` tenant nobody created would be a
            # tenant nobody can see the membership of.
            await self.tenants.seed_local_tenant()
        if self._initial_project_id is not None:
            await self.attach_project(self._initial_project_id)

    async def _sweep_reconciliation(self) -> None:
        """Re-run reconciliation forever, on a jittered timer.

        `BACKLOG.md` B99, closed by this; the three questions it deferred on
        are answered here and in the spec `start()` names.

        **Full jitter: the sleep is a uniform draw from `[0, interval]`, not
        the interval itself.** That is the standard answer to the failure it
        prevents -- every process in a multi-instance deployment sweeping in
        lockstep, which turns a cheap periodic read into a synchronised burst
        against one database, and keeps them synchronised because they all
        wake, work, and sleep the same amount. The cost is that an individual
        sweep's spacing is unpredictable and averages half the interval, so
        the configured number is an upper bound on the gap rather than the gap.
        Sleeping *before* the first sweep is deliberate: `start()` has just run
        one, and a sweep immediately after it would be pure waste.

        **Two processes sweeping the same proposal at once needs no locking,
        and that is a claim about `StoreMediaProposal` rather than about
        timing.** It *refuses* an already-stored proposal instead of being
        idempotent, and `MediaAcceptWorker` reads that refusal back as its own
        success signal -- so the loser of a race records nothing and reports
        success. The cost of not locking is a duplicated download, bounded by
        the number of processes; the blob store is content-addressed, so the
        bytes land on the same blob and nothing downstream can tell.

        Survives a sweep raising, because the timer is worth more than any one
        sweep: a projection that is briefly unreadable would otherwise kill
        reconciliation for the life of the process, silently, which is the
        exact defect B99 is about. `asyncio.CancelledError` is a
        `BaseException` and so is *not* caught here -- deliberately, and the
        reason for `except Exception` rather than a bare `except`: a sweep
        that swallowed cancellation would outlive `close()`.
        """
        while True:
            await asyncio.sleep(random.uniform(0, self.media_reconcile_interval))
            try:
                await self.media_accept_reconciler.run()
            except Exception:
                logger.exception("periodic media reconciliation sweep failed")

    def turns_tools(self) -> tuple[BaseTool, ...]:
        """The tools available to this instance's agent, for tests that assert on them.

        Reads through SessionService's public tools property rather than reaching
        into private attributes (BACKLOG B8)."""
        return self.service.tools

    async def summaries_caught_up(self) -> None:
        """Wait until the `/sessions` projection has seen everything appended.

        The read model is eventually consistent by construction -- a turn
        commits to the log and the projection follows -- which is invisible to
        a person clicking around and maddening to a test. This is the seam that
        makes the lag addressable rather than something to sleep through.
        """
        await self.summaries.caught_up()

    async def topics_caught_up(self) -> None:
        """Block until the topic tables have seen everything appended so far.

        Load-bearing rather than a test affordance, for the reason the corpus
        equivalent is: an autonomous round records a look and then asks for the
        next topic, and the gap between the append and the row is exactly where
        it would be handed back the topic it just finished.
        """
        await self.topics.caught_up()

    async def corpus_caught_up(self) -> None:
        """Wait until the corpus projection has seen everything appended.

        The same seam `summaries_caught_up` provides, for the same reason: a
        `remember` commits to the log and the table follows, so a caller that
        stores a document and immediately lists it would otherwise be racing
        the projection.
        """
        await self.corpus.caught_up()

    async def interaction_log_caught_up(self) -> None:
        """Wait until `interaction_events` has seen every appended event.

        For tests. Nothing in production waits on this -- the browser is not
        told when its batch landed, and could not use the answer.
        """
        await self.interaction_log.caught_up()

    async def reconciled(self) -> None:
        """Wait until startup reconciliation has finished, if it was scheduled.

        The same seam `summaries_caught_up` is, and for the same reason: the
        work is deliberately off the startup path, which is invisible to a
        person and untestable without this -- and a reconciliation observable
        only by sleeping is one that would rot.

        Returns immediately if `start()` has not run. Never raises what the
        reconciliation hit: `MediaAcceptReconciler.run` is total by
        construction (its docstring says why), so there is nothing here to
        re-raise.
        """
        for task in self._reconciliation:
            await task

    async def close(self) -> None:
        """Stop anything still running, then let go of the store.

        Cancelling first means an in-flight turn unwinds into a recorded
        failure rather than being abandoned mid-write. The projection stops
        before the store it reads through does, for the same reason.
        `detach_project` is safe to call whether or not anything is attached.

        Runs stop before turns do, and that order is the point: a run asked to
        stop finishes the round it is in, and a turn cancelled underneath it
        would make that round a recorded failure rather than the last one. The
        wait is bounded by whatever the in-flight turn takes.
        """
        # Reconciliation is cancelled rather than awaited, and it goes first
        # because it reads through the projections and the store stopped
        # below. Cancelling loses nothing: the proposal it was working on
        # stays `accepted`, which is precisely the state the next `start()`
        # reconciles -- whereas awaiting would hold shutdown for as long as
        # the download it is in the middle of.
        for task in self._reconciliation:
            task.cancel()
        self._reconciliation.clear()
        # The periodic sweep goes with it, and for a stronger reason: it never
        # finishes on its own, so anything short of cancelling it here leaves a
        # task reading through a stopped projection and a closed store for the
        # life of the event loop. Cancelled rather than awaited for the same
        # reason as above -- mid-download it would hold shutdown, and the
        # proposal it abandons stays `accepted`, which the next sweep or the
        # next `start()` reconciles.
        for task in self._sweep:
            task.cancel()
        self._sweep.clear()
        # Every step runs, whatever the ones before it did (B10). The list was
        # a straight run of `await`s, so the first raise skipped everything
        # under it -- and the two things furthest down are the ones that leak
        # hardest: `detach_project` releases a Neo4j driver, and `close_all`
        # releases every graph store this instance ever opened. A shutdown
        # path that stops at the first problem is a shutdown path that leaks
        # most when something has already gone wrong, which is exactly when
        # nobody is reading the traceback.
        #
        # Order is unchanged and still load-bearing: stops before cancels
        # (see above), projections before the store they read through, and the
        # two graph releases last. Failures are collected rather than dropped
        # and re-raised together at the end, so `close()` still fails loudly --
        # swallowing them would turn one leak into a silent one.
        await _close_every_step(
            ("research", self.research.stop_all),
            ("turns", self.turns.cancel_all),
            ("summaries", self.summaries.stop),
            ("corpus", self.corpus.stop),
            ("topics", self.topics.stop),
            ("definitions", self.definitions.stop),
            ("ontology", self.ontology.stop),
            # Grouped with the projections above rather than beside the
            # interaction log, which it superficially resembles: those two
            # follow *different* stores, and this one follows the sessions
            # store like its four neighbours here. It has to stop before
            # `service` closes that store underneath it.
            ("tenants", self.tenants.stop),
            ("catalog", self._catalog_runner.stop),
            ("course", self._course_runner.stop),
            ("blurb cache", self._blurb_cache.close),
            ("outline cache", self._outline_cache.close),
            ("art store", self.art_store.close),
            ("candidate art store", self._candidate_art_store.close),
            ("project summaries", self.project_summaries.close),
            ("media proposals", self.media_proposals.stop),
            ("asks", self.asks.stop),
            ("authoring", self.authoring.stop),
            ("dialogues", self.dialogues.stop),
            ("users", self.users.stop),
            ("interaction log", self.interaction_log.stop),
            ("interaction store", self._interaction_store.close),
            # Both settings stores, as one step -- see `SettingsDeps.close`.
            # New here as of W-C2 and not optional: until this branch the
            # override table was opened only by a settings *route*, so almost
            # no test ever opened it and the omission cost nothing. Resolution
            # now happens at `open_graph`, which every attach reaches, so the
            # connection is opened in nearly every test -- and `aiosqlite`'s
            # worker thread is non-daemon, so leaking one per test is a
            # process that runs the suite and then never exits.
            ("settings", self.settings.close),
            ("service", self.service.close),
            # Unconditional, whether this client was built here or handed in
            # by a test: whoever built it, `Application` owns it for its
            # lifetime, and an unclosed `httpx.AsyncClient` leaks its
            # connection pool.
            ("media http client", self._media_http_client.aclose),
            ("attached project", self.detach_project),
            # Every project this instance ever opened a graph for, not just
            # the one that happened to be attached -- `detach_project` above
            # only releases that one, and a read route can have opened others
            # through `graphs` directly without ever attaching them.
            ("graphs", self.graphs.close_all),
        )
