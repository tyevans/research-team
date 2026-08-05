"""`/project` (list) and `/project new <name>` (create) at the REPL.

Follows the harness `test_repl.py` already uses: the `current` fixture builds
a `Repl` over a fresh in-memory-backed service, and commands run through
`repl.handle_command` directly rather than a higher-level runner.
"""

import pytest

from research_team.interfaces.cli import repl


@pytest.fixture
async def current(build_service, fake_model):
    """A REPL pointed at a fresh session -- the terminal owns the cursor.

    Duplicated from `test_repl.py`'s fixture of the same name rather than
    shared, because that fixture is module-local, not in `conftest.py`.
    """
    return await repl.Repl.start(await build_service(model=fake_model))


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


async def test_listing_with_no_projects_says_so(current):
    output = await repl.handle_command(current, "/project")

    assert "no projects" in output.lower()


async def test_project_use_reports_an_unknown_name(current):
    output = await repl.handle_command(current, "/project use nope")

    assert "nope" in output and "no such project" in output.lower()


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
    """
    await repl.handle_command(current, "/project new research")
    await repl.handle_command(current, "/project use research")

    await repl.handle_command(current, "/new")
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
