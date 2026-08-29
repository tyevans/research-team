#!/bin/sh
# Pick up the OIDC client the Zitadel bootstrap provisioned, if it ran.
#
# Zitadel mints the client id and secret itself -- neither can be chosen ahead
# of time, and neither is knowable from a compose file -- so the bootstrap
# container creates the application through Zitadel's API and writes the pair
# here. This script is the seam: it sources the file when it exists and runs
# unchanged when it does not.
#
# **Only when the variables are not already set.** An operator pointing this
# image at a real identity provider passes `AGENT_OIDC_CLIENT_ID` in the
# environment, and a stale file from a previous local run silently overriding
# that would be a genuinely dangerous surprise -- the app would authenticate
# against the wrong issuer and every sign-in would fail with a claim error
# naming nothing about a leftover file.
set -e

BOOTSTRAP_ENV="${AGENT_BOOTSTRAP_ENV:-/bootstrap/oidc.env}"

if [ -z "${AGENT_OIDC_CLIENT_ID}" ] && [ -f "${BOOTSTRAP_ENV}" ]; then
    # shellcheck disable=SC1090 - the path is configuration, not a literal
    . "${BOOTSTRAP_ENV}"
    export AGENT_OIDC_CLIENT_ID AGENT_OIDC_CLIENT_SECRET
    echo "app-entrypoint: using the OIDC client from ${BOOTSTRAP_ENV}" >&2
fi

exec "$@"
