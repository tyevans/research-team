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


async def test_project_use_is_not_available_yet(current):
    output = await repl.handle_command(current, "/project use research")

    assert "not available" in output.lower()


async def test_project_help_mentions_the_command(current):
    output = await repl.handle_command(current, "/help")

    assert "/project" in output
