"""Process entrypoint: build the application, then hand it to the REPL."""

import asyncio

from research_team.composition import build_service
from research_team.interfaces.cli import run


def main() -> None:
    asyncio.run(run(build_service()))


if __name__ == "__main__":
    main()
