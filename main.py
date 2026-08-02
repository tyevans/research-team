"""Process entrypoint: build the application, then hand it to the REPL."""

import asyncio

from research_team.composition import build_service
from research_team.interfaces.cli import run


async def _main() -> None:
    await run(await build_service())


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
