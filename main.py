"""Process entrypoint: build the application, then hand it to the REPL."""

import asyncio

from research_team.composition import build_application
from research_team.interfaces.cli import TerminalApprovals, run


async def _run() -> None:
    """Start the application inside the loop that will use it, then serve.

    `/sessions` is backed by a projection holding its own connection, and
    aiosqlite binds a connection to the loop that opened it -- so starting has
    to happen in here, not around `asyncio.run`.
    """
    application = build_application(approvals=TerminalApprovals())
    await application.start()
    try:
        await run(application.service, application.policy, application.research)
    finally:
        await application.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
