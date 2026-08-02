import asyncio

from research_team.repl import main as repl_main


def main() -> None:
    asyncio.run(repl_main())


if __name__ == "__main__":
    main()
