"""Lifecycle and teardown helpers for application wiring and partial-build unwinding."""

import asyncio
import contextlib
import types
from collections.abc import Awaitable, Callable, Sequence

#: Every local in `_build_application` that owns something needing releasing,
#: paired with how to release it, in `Application.close`'s order. A name list
#: rather than duck-typing over the frame, because half the locals in there are
#: caller-injected and closing a `media_http_client` a test still owns would
#: turn one leak into a different bug.
#:
#: `resolved_media_http_client` is deliberately absent. `Application.close`
#: closes it whether or not the caller supplied it -- correct there, because an
#: `Application` exists and owns it for its lifetime -- but on a partial build
#: no `Application` exists, and the caller's client is still the caller's.
#: B98's ordering already means an un-injected one is never constructed before
#: the return.
#:
#: **What breaks this, and why the failure is the worst possible shape.** These
#: are the names of another function's local variables. Nothing in Python ties
#: them to the assignments in `_build_application`: rename `corpus` there and
#: this entry stops matching, `frame.f_locals.get` returns `None`, the resource
#: is quietly dropped from the teardown, and the build still raises exactly as
#: it did before. The leak comes back, silently, looking identical to the leak
#: this constant exists to prevent -- and it comes back at the moment someone
#: is refactoring, which is when they are least likely to be reading this.
#:
#: So the names are not left to a comment.
#: `test_every_partial_build_resource_is_a_local_of_the_build` parses
#: `_build_application` and asserts every name here is assigned in it, which
#: turns a rename into a red test rather than a returned leak. Read that test
#: before editing this tuple; it is the contract, and this paragraph is only
#: the reason for it.
#:
#: The other direction is covered too, since B179, and this paragraph used to
#: say it could not cheaply be. It can: the `Application(...)` call at the end
#: of `_build_application` already maps each attribute to the local that filled
#: it, so `test_every_close_step_has_a_partial_build_resource` resolves every
#: `self.<attr>.<method>` step in `Application.close` back to a `(local,
#: method)` pair and asserts it is declared here. Two steps deliberately do not
#: resolve -- `_media_http_client.aclose` and `detach_project` -- and both are
#: exempted by name with their reason, under an exemption-staleness test.
#:
#: That direction is the one that actually fired: a branch adding a resource to
#: `close()` *conflicts* there, because `close()` is edited often, and does not
#: conflict here, because it never touched this tuple -- so the merge machinery
#: is silent about the half that matters. Order is still kept in step with
#: `close()` deliberately, for the reader; the test is what enforces membership.
_PARTIAL_BUILD_RESOURCES: tuple[tuple[str, str], ...] = (
    ("research_supervisor", "stop_all"),
    ("turns", "cancel_all"),
    ("summaries", "stop"),
    ("corpus", "stop"),
    ("topics", "stop"),
    ("definition_invalidation", "stop"),
    ("ontology", "stop"),
    # Beside the other sessions-store projections, mirroring `Application.close`
    # -- the two lists are kept in the same order deliberately, since the
    # comment above says the "in close but not here" direction has no compiler
    # between them and ordering is the only thing a reader can diff by eye.
    #
    # Reachable but currently inert, and worth saying which: a `TenantRunner`
    # holds nothing until `start()`, and `_build_application` only constructs
    # it, so `stop()` on a partial build is a no-op today. It is listed anyway,
    # because "this one happens to hold no resources yet" is a fact about this
    # week rather than about the design, and the omission would be found the
    # first time that changed -- by a hung interpreter, not by a test.
    ("tenants", "stop"),
    ("catalog_runner", "stop"),
    ("course_runner", "stop"),
    ("blurb_cache", "close"),
    ("outline_cache", "close"),
    ("art_store", "close"),
    ("candidate_art_store", "close"),
    ("project_summaries", "close"),
    ("media_proposals", "stop"),
    ("asks", "stop"),
    ("authoring", "stop"),
    ("dialogues", "stop"),
    # In `close()`'s order, beside `dialogues` and before the interaction log,
    # for the reason the `tenants` comment above gives: the two lists have no
    # compiler between them, so matching order is the only thing a reader can
    # diff by eye.
    #
    # Unlike `tenants`, this one is not inert. A started `UserRunner` holds an
    # aiosqlite connection, a `SubscriptionManager` and a SQLAlchemy engine, so
    # a build that raises after it is constructed abandons all three -- which
    # presents as a hung interpreter at exit and nothing red. This was the
    # third instance of the same omission in one day (a tenants runner and a
    # project-summaries port preceded it) and the first one a test caught
    # rather than a reader.
    ("users", "stop"),
    ("interaction_log", "stop"),
    ("interaction_store", "close"),
    # In `close()`'s order, between the interaction store and the service.
    # Holds two aiosqlite connections, both opened lazily -- so a partial build
    # that raises before either is touched abandons nothing, and one that
    # raises after `open_graph` ran abandons two non-daemon worker threads.
    # `SettingsDeps.close` is a no-op on an unopened store, which is what makes
    # it safe to list unconditionally.
    ("settings_deps", "close"),
    ("service", "close"),
    ("graphs", "close_all"),
    # Last, and the one B100 is really about: `EventStoreSessionRepository`
    # holds the SQLite event store, whose aiosqlite worker thread is
    # non-daemon (B5). A partial build that abandons it does not merely leak
    # memory -- it parks the interpreter in `threading._shutdown` waiting for
    # a thread that will never finish, so a misconfiguration that should have
    # raised cleanly hangs the process instead.
    ("repository", "close"),
)


async def _close_every_step(*steps: tuple[str, Callable[[], Awaitable[object]]]) -> None:
    """Run every teardown step, then raise whatever any of them raised.

    Shared by `Application.close` (B10) and `build_application`'s unwind
    (B100), which want the same two properties and would otherwise each grow
    their own `try/finally` ladder: nothing is skipped because something
    earlier failed, and nothing is swallowed.

    `BaseException` rather than `Exception`, deliberately: a teardown step that
    is itself cancelled must not take the remaining steps down with it, which
    is the case `Application.close` meets when a shutdown races a
    `KeyboardInterrupt`. The cancellation is re-raised in the group at the end,
    so it is not lost -- it just stops being a reason to leak a Neo4j driver.

    Raises an `ExceptionGroup` even for a single failure. Uniform on purpose:
    a caller that has to handle two shapes handles one of them wrong, and the
    old behaviour -- one bare exception, and everything after it silently not
    run -- is what this exists to end.
    """
    failures: list[BaseException] = []
    for name, step in steps:
        try:
            await step()
        except BaseException as error:  # noqa: BLE001 -- collected, then re-raised below
            error.add_note(f"raised while closing: {name}")
            failures.append(error)
    if failures:
        raise BaseExceptionGroup("teardown failed", failures)


def _partial_build_teardown(
    error: BaseException,
    target_code: types.CodeType | None = None,
    resources: Sequence[tuple[str, str]] = _PARTIAL_BUILD_RESOURCES,
) -> tuple[tuple[str, Callable[[], Awaitable[object]]], ...]:
    """Everything `_build_application` had opened when it raised.

    Read out of the raising frame's locals rather than from a registry the
    function appends to as it builds. The registry is the tidier design and
    was rejected on cost: it is a line at each of two dozen construction sites
    spread over 1400 lines of a file three other branches are editing, where
    this is one place. What it buys with that is honesty about its own
    weakness -- a name that gets renamed silently stops being torn down, which
    a registry could not do.
    """
    frame = None
    traceback = error.__traceback__
    while traceback is not None:
        if (target_code is not None and traceback.tb_frame.f_code is target_code) or (
            target_code is None and traceback.tb_frame.f_code.co_name == "_build_application"
        ):
            frame = traceback.tb_frame
        traceback = traceback.tb_next
    if frame is None:
        return ()
    steps: list[tuple[str, Callable[[], Awaitable[object]]]] = []
    for name, method in resources:
        resource = frame.f_locals.get(name)
        if resource is not None and callable(getattr(resource, method, None)):
            steps.append((name, getattr(resource, method)))
    return tuple(steps)


#: Strong references to in-flight detached teardowns; see `_run_detached`.
_DETACHED_TEARDOWNS: set[asyncio.Task] = set()


def _run_detached(work: Awaitable[None]) -> None:
    """Run a teardown coroutine from synchronous code, loop or no loop.

    Exceptions are swallowed here and nowhere else in this module: this runs
    while another exception is already propagating, and a failure to close
    something must not replace the misconfiguration the caller actually needs
    to read. `_close_every_step` names each failed step in the group it
    raises, so the detail is not gone -- it is just not this path's to report.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_swallowing(work))
        return
    # Held in a module-level set until it finishes. `create_task` keeps only a
    # weak reference, so a teardown task with no other owner can be collected
    # mid-close -- which is the leak this function exists to prevent, arriving
    # by a different door.
    task = loop.create_task(_swallowing(work))
    _DETACHED_TEARDOWNS.add(task)
    task.add_done_callback(_DETACHED_TEARDOWNS.discard)


async def _swallowing(work: Awaitable[None]) -> None:
    with contextlib.suppress(BaseException):
        await work
