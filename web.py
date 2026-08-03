"""Process entrypoint for the web UI: build the application, serve it."""

import uvicorn

from research_team.composition import build_application
from research_team.infrastructure import config
from research_team.interfaces.web import create_app


def main() -> None:
    application = build_application()
    uvicorn.run(
        create_app(application.service, application.feed),
        host=config.web_host(),
        port=config.web_port(),
    )


if __name__ == "__main__":
    main()
