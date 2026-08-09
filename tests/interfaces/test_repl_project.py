"""`/project` (list) and `/project new <name>` (create) at the REPL.

Follows the harness `test_repl.py` already uses: the `current` fixture builds
a `Repl` over a fresh in-memory-backed service, and commands run through
`repl.handle_command` directly rather than a higher-level runner.
"""

import pytest

from research_team.interfaces.cli import repl
from tests.conftest import start_session


@pytest.fixture
async def current(build_service, fake_model):
    """A REPL pointed at a fresh session -- the terminal owns the cursor.

    Duplicated from `test_repl.py`'s fixture of the same name rather than
    shared, because that fixture is module-local, not in `conftest.py`. Like
    that one, it supplies the session `Repl.start` no longer can: these tests
    are about what `/project` does, not about how a terminal gets its first
    session, which `test_repl.py` covers on its own.
    """
    current = await repl.Repl.start(await build_service(model=fake_model))
    current.session_id = await start_session(current.service)
    return current


async def test_project_new_creates_and_reports(current):
    output = await repl.handle_command(current, "/project new research")

    assert "research" in output


async def test_project_lists_what_exists(current):
    await repl.handle_command(current, "/project new research")
    await repl.handle_command(current, "/project new archive")

    output = await repl.handle_command(current, "/project")

    assert "research" in output and "archive" in output


async def test_creating_a_project_twice_reports_the_collision(current):
    await repl.handle_command(current, "/project new research")

    output = await repl.handle_command(current, "/project new research")

    assert "research" in output and "already" in output.lower()

    # The collision must have actually been rejected, not merely worded as
    # one: the listing still shows exactly one "research" project.
    listing = await repl.handle_command(current, "/project")
    assert listing.count("research") == 1


async def test_listing_with_no_projects_says_so(build_service, fake_model):
    """Not the `current` fixture: its session comes with a project of its own,
    so an empty listing is only observable on a REPL that has neither. That is
    exactly the state a terminal opens in now, which is the case worth naming."""
    fresh = await repl.Repl.start(await build_service(model=fake_model))

    output = await repl.handle_command(fresh, "/project")

    assert "no projects" in output.lower()


async def test_project_use_reports_an_unknown_name(current):
    output = await repl.handle_command(current, "/project use nope")

    assert "nope" in output and "no such project" in output.lower()


async def test_project_use_attaches_the_knowledge_graph(build_application, fake_model):
    """The gap Task 14 closes: `/project use` must make `remember` reachable.

    Goes through a whole `Application`, not just a `SessionService`, because
    the tools live on the executor `build_application` wires -- the same
    object `/project use` has to reach through the service to swap. Before
    this task, nothing called `attach_project` at all: `build_application`
    only ever attached a graph when given `project_id=` at construction, and
    `/project use` had no way to attach one to an application already built.
    """
    application = await build_application(model=fake_model)
    current = await repl.Repl.start(application.service)
    current.session_id = await start_session(application.service)

    await repl.handle_command(current, "/project new research")
    await repl.handle_command(current, "/project use research")

    names = {tool.name for tool in application.turns_tools()}
    assert "remember" in names


async def test_project_use_starts_a_session_in_the_project(current):
    """Assert wording only a successful join produces.

    "research" alone is not enough: `'research': no such project` -- the
    failure message -- also contains it, so that assertion would pass on an
    implementation that never actually started a session.
    """
    before = current.session_id
    await repl.handle_command(current, "/project new research")

    output = await repl.handle_command(current, "/project use research")

    assert "joined project research" in output
    assert current.session_id != before


async def test_a_second_session_cannot_take_a_held_project(current):
    await repl.handle_command(current, "/project new research")
    await repl.handle_command(current, "/project use research")

    output = await repl.handle_command(current, "/project use research")

    assert "held by" in output.lower()


async def test_project_help_mentions_the_command(current):
    output = await repl.handle_command(current, "/help")

    assert "/project" in output


async def test_switching_sessions_releases_a_held_project(current):
    """Regression for the leak found in review: switching away from a
    session that holds a project must free it, not just quitting.

    Without `_switch_to` releasing the outgoing session's project, this
    second `/project use` would report "held by" forever -- there was no
    command that could clear it.

    Switching away is a join of a second project now. It used to be `/new`,
    which no longer switches anything; joining another project is the same
    switch by the path a person actually takes.
    """
    await repl.handle_command(current, "/project new research")
    await repl.handle_command(current, "/project new archive")
    await repl.handle_command(current, "/project use research")

    await repl.handle_command(current, "/project use archive")
    output = await repl.handle_command(current, "/project use research")

    assert "joined project research" in output


async def test_exiting_the_repl_releases_a_held_project(
    build_service, fake_model, monkeypatch
):
    """`run()`'s exit path calls `release_project`, not merely `service.close()`.

    Drives through `run()` itself with scripted `input` lines, so this pins
    the actual exit path rather than assuming it matches what
    `handle_command` does when called directly. `run()` builds its own
    `Repl` internally (`Repl.start`), so the project is joined from inside
    the scripted session rather than handed to it from outside.
    """
    import asyncio

    async def fake_to_thread(fn, *args):
        return fn(*args)

    lines = iter(["/project new research", "/project use research", "/quit"])
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr("builtins.input", lambda *_: next(lines))

    service = await build_service(model=fake_model)
    await repl.run(service)

    # `run()` closes `service`; a second one over the same store proves the
    # project was actually released, not just that `run()` returned.
    other_service = await build_service(model=fake_model)
    project_id = (await other_service.list_projects())[0][0]
    joined = await other_service.start_in_project(project_id)
    assert joined is not None


async def test_resuming_a_project_session_reattaches_its_knowledge_graph(
    build_application, fake_model
):
    """`/resume` into a project session must not leave it without the graph
    its own recorded prompt describes.

    `_switch_to` detaches unconditionally on every switch (whatever was
    attached belonged to the outgoing session), so a session resumed back
    into a project needs its own re-attach -- otherwise the model is told
    about `remember`/`graph_search`/`unmerge` by its `SessionStarted` prompt
    while the executor no longer has them. Reattaching must not re-acquire
    the project's filesystem lease: that is `/project use`'s job (via
    `start_in_project`'s `JoinProject`), not a side effect of merely looking
    at an old session again, or every `/resume` into a project would fight
    over who holds it.
    """
    application = await build_application(model=fake_model)
    current = await repl.Repl.start(application.service)
    current.session_id = await start_session(application.service)

    await repl.handle_command(current, "/project new research")
    await repl.handle_command(current, "/project new archive")
    await repl.handle_command(current, "/project use research")
    project_session_id = current.session_id

    # Switch away: this detaches "research"'s graph and releases its lease, so
    # "research" has no holder afterwards. Joining a second project rather
    # than `/new`, which no longer switches sessions at all -- and the switch
    # is observed as *which* graph is attached rather than as no graph at all,
    # because every session has a project now, so there is no session to land
    # on that leaves the executor without knowledge tools.
    archive_id = next(
        pid for pid, name in await application.service.list_projects() if name == "archive"
    )
    await repl.handle_command(current, "/project use archive")
    assert application.service.attached_project_id == archive_id

    output = await repl.handle_command(current, f"/resume {project_session_id}")

    assert "error" not in output.lower()
    names = {tool.name for tool in application.turns_tools()}
    assert "remember" in names

    # Resuming looked at the session, it did not take the project back.
    project_id = next(
        pid for pid, name in await application.service.list_projects() if name == "research"
    )
    assert application.service.attached_project_id == project_id
    project = await application.service.projects.load(project_id)
    assert project.state.active_session_id is None
