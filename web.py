"""Process entrypoint for the web UI: build the application, serve it."""

from contextlib import asynccontextmanager

import uvicorn

from research_team.composition import build_application
from research_team.infrastructure import config
from research_team.interfaces.web import create_app


def main() -> None:
    application = build_application()

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
        create_app(application.service, application.feed, application.turns, lifespan),
        host=config.web_host(),
        port=config.web_port(),
    )


if __name__ == "__main__":
    main()
