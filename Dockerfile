# The app as a container, for `docker compose up`.
#
# Two stages, and the split exists for one reason: **the console must be built
# into the image.** `create_app` mounts nothing when
# `research_team/interfaces/web/static` is absent and `/` answers 503 naming
# the command -- so an image without a Node stage starts cleanly, serves the
# whole API, and has no UI, which is the most confusing possible half-working
# state. CLAUDE.md's note that the built console is no longer committed is
# exactly what makes this stage mandatory rather than a convenience.
#
# The Node stage is discarded: nothing at runtime needs npm, and carrying it
# would roughly double the image for files only the build used.

FROM node:22-slim AS console

WORKDIR /frontend
# `package*.json` first, so a change to a `.tsx` file does not invalidate the
# dependency layer. `npm ci` rather than `npm install`, for the reason the
# repository already knows: `install` rewrites the lockfile, and a lockfile
# written by a different npm than CI's makes `npm ci` fail there and skip
# every frontend gate.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# `vite build` writes into `../research_team/interfaces/web/static`, which is
# outside this stage's `WORKDIR` -- so the tree the build writes into has to
# exist. Created rather than copied from the repository, because it is
# gitignored and would not be there to copy.
RUN mkdir -p /research_team/interfaces/web && npm run build


FROM python:3.13-slim AS app

# `uv` from its own image rather than `pip install uv`: it is a single static
# binary, and copying it costs one layer against a pip resolution that would
# run on every build.
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies before source, same layering argument as npm above.
# `--frozen` refuses to update the lockfile: an image whose dependency set
# differs from `uv.lock` is an image nothing else in this project has ever
# tested against.
#
# `--no-install-project` because this project declares no `[build-system]`
# (see `pythonpath` in `pyproject.toml`) -- there is nothing to install, and
# `WORKDIR` on `sys.path` is how imports resolve here and in CI alike.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY research_team/ ./research_team/
COPY web.py main.py ./
COPY --from=console /research_team/interfaces/web/static ./research_team/interfaces/web/static

# `0.0.0.0`, not the `127.0.0.1` default: a server bound to loopback inside a
# container is reachable from nothing, including the published port. This is
# the one setting that has to differ from a host run, and it is set here
# rather than in `docker-compose.yml` so that the image is runnable on its own.
ENV AGENT_WEB_HOST=0.0.0.0 \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# The bootstrap credentials, when there are any. `docker-compose.yml` mounts a
# volume the Zitadel bootstrap writes `oidc.env` into; this sources it if it
# exists and runs unchanged if it does not, which is what keeps the image
# usable with `AGENT_AUTH=off` and no IdP at all.
COPY docker/app-entrypoint.sh /usr/local/bin/app-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/app-entrypoint.sh"]
CMD ["python", "web.py"]
