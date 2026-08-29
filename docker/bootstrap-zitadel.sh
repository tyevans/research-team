#!/bin/sh
# Provision the project and the OIDC client this app signs in against.
#
# **Why this container exists at all.** Zitadel's `FirstInstance` settings can
# declare an instance, an organisation, a human admin and a machine user, all
# from environment variables -- and that is as far as declarative provisioning
# goes. A *project* and an *application* have to be created through the
# management API, and more importantly the client id and client secret are
# minted by Zitadel: neither can be chosen in advance, so neither can be
# written into `docker-compose.yml`. Something has to create them and tell the
# app what they are, and this is that something.
#
# The credential it uses is the PAT that Zitadel writes for the machine user
# named in `ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*`. That user is created with
# `IAM_OWNER`, which is far more than this needs and is what `FirstInstance`
# offers; scoping it down means a second API call to change roles, against a
# token that is only reachable inside a local development stack.
#
# **Idempotent, because compose restarts things.** Every run checks for the
# project and the application by name before creating them, and a run that
# finds both rewrites the env file from what already exists. Without that, a
# `docker compose up` after a crash would create a second application, the app
# would keep using the first one's credentials from the env file, and sign-in
# would fail with `invalid_client` -- an error naming nothing about a
# duplicate.
set -eu

ZITADEL_API="${ZITADEL_API:-http://zitadel:8080}"
# Every management request is answered by the *instance* matching the `Host`
# header, and this instance's domain is the one the browser uses, not the
# compose service name. Without this header Zitadel answers 404 for an
# instance it cannot find -- which reads exactly like a wrong path.
ZITADEL_HOST_HEADER="${ZITADEL_HOST_HEADER:-localhost:8081}"
PAT_FILE="${PAT_FILE:-/machine/pat.txt}"
OUT_FILE="${OUT_FILE:-/bootstrap/oidc.env}"
PROJECT_NAME="${PROJECT_NAME:-research-team}"
APP_NAME="${APP_NAME:-console}"
APP_BASE_URL="${APP_BASE_URL:-http://localhost:8000}"

log() { echo "bootstrap-zitadel: $*" >&2; }

# Wait for the PAT rather than for the port. The API answers before
# `FirstInstance` has finished, so a readiness check on HTTP would let this
# run against an instance with no machine user and fail on the first
# authenticated call.
attempt=0
while [ ! -s "${PAT_FILE}" ]; do
    attempt=$((attempt + 1))
    if [ "${attempt}" -gt 120 ]; then
        log "gave up waiting for ${PAT_FILE} -- did zitadel finish its first-instance setup?"
        exit 1
    fi
    sleep 2
done
PAT="$(cat "${PAT_FILE}")"

api() {
    method="$1"
    path="$2"
    body="${3:-}"
    if [ -n "${body}" ]; then
        curl -sS -X "${method}" "${ZITADEL_API}${path}" \
            -H "Host: ${ZITADEL_HOST_HEADER}" \
            -H "Authorization: Bearer ${PAT}" \
            -H "Content-Type: application/json" \
            -d "${body}"
    else
        curl -sS -X "${method}" "${ZITADEL_API}${path}" \
            -H "Host: ${ZITADEL_HOST_HEADER}" \
            -H "Authorization: Bearer ${PAT}"
    fi
}

# The API can be up while the instance is still settling; retry the first real
# call rather than the health endpoint, for the reason above.
attempt=0
until api GET /management/v1/projects/_search >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "${attempt}" -gt 60 ]; then
        log "the management API never answered -- check the zitadel container's logs"
        exit 1
    fi
    sleep 2
done

projects="$(api POST /management/v1/projects/_search '{"queries":[]}')"
project_id="$(echo "${projects}" | jq -r --arg name "${PROJECT_NAME}" \
    '.result // [] | map(select(.name == $name)) | .[0].id // empty')"

if [ -z "${project_id}" ]; then
    log "creating project ${PROJECT_NAME}"
    project_id="$(api POST /management/v1/projects \
        "$(jq -nc --arg name "${PROJECT_NAME}" '{name: $name}')" | jq -r '.id')"
fi
log "project ${PROJECT_NAME} is ${project_id}"

apps="$(api POST "/management/v1/projects/${project_id}/apps/_search" '{"queries":[]}')"
app_id="$(echo "${apps}" | jq -r --arg name "${APP_NAME}" \
    '.result // [] | map(select(.name == $name)) | .[0].id // empty')"

if [ -z "${app_id}" ]; then
    log "creating OIDC application ${APP_NAME}"
    # A *confidential* web client: `OIDC_AUTH_METHOD_TYPE_BASIC` means a
    # secret is minted and required at the token endpoint. PKCE is sent as
    # well -- the two are complementary, not alternatives, and Zitadel accepts
    # a code challenge from a confidential client without being told to.
    #
    # `devMode: true` is what allows a plain-`http` redirect URI. It is a
    # local-development-only setting, and it is the single line in this stack
    # that must not survive into anything reachable from outside a laptop.
    created="$(api POST "/management/v1/projects/${project_id}/apps/oidc" "$(
        jq -nc \
            --arg name "${APP_NAME}" \
            --arg redirect "${APP_BASE_URL}/auth/callback" \
            --arg logout "${APP_BASE_URL}/" \
            '{
                name: $name,
                redirectUris: [$redirect],
                postLogoutRedirectUris: [$logout],
                responseTypes: ["OIDC_RESPONSE_TYPE_CODE"],
                grantTypes: ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE"],
                appType: "OIDC_APP_TYPE_WEB",
                authMethodType: "OIDC_AUTH_METHOD_TYPE_BASIC",
                accessTokenType: "OIDC_TOKEN_TYPE_BEARER",
                devMode: true
            }'
    )")"
    app_id="$(echo "${created}" | jq -r '.appId')"
    client_id="$(echo "${created}" | jq -r '.clientId')"
    client_secret="$(echo "${created}" | jq -r '.clientSecret')"
else
    # The application exists, so its secret is not retrievable -- Zitadel
    # returns a secret exactly once, at creation or regeneration. Regenerating
    # is the only way to get a usable pair back, and it is safe here precisely
    # because the only consumer is the app container this script writes the
    # file for.
    log "application ${APP_NAME} already exists; regenerating its secret"
    detail="$(api GET "/management/v1/projects/${project_id}/apps/${app_id}")"
    client_id="$(echo "${detail}" | jq -r '.app.oidcConfig.clientId')"
    # `_generate_client_secret`, not `_regenerate_clientsecret`. The RPC is
    # `RegenerateOIDCClientSecret` and the path is not named after it --
    # guessing from the method name gives a 404 whose body is
    # `{"code":5,"message":"Not Found"}`, which reads exactly like a wrong app
    # id. Taken from `proto/zitadel/management.proto` at the pinned tag, and
    # confirmed against a running instance on 2026-08-29.
    #
    # Note the id in the path is the **app id**, not the client id. Zitadel
    # returns both and they are different numbers of the same shape, so
    # swapping them also produces a 404 that looks like a permissions problem.
    client_secret="$(api POST \
        "/management/v1/projects/${project_id}/apps/${app_id}/oidc_config/_generate_client_secret" \
        '{}' | jq -r '.clientSecret')"
fi

# Both halves checked, and the secret is the one that matters. A `null` here
# means an API call answered a shape this script did not expect -- which is
# how the regenerate path shipped broken once: the id was correct, the secret
# was the literal string `null`, and the env file was written anyway. The app
# then started, discovered the issuer, and failed at the token endpoint with
# `invalid_client` on the first sign-in, minutes later and nowhere near the
# cause. Failing here is the difference.
for pair in "client id:${client_id}" "client secret:${client_secret}"; do
    label="${pair%%:*}"
    value="${pair#*:}"
    if [ -z "${value}" ] || [ "${value}" = "null" ]; then
        log "no ${label} came back -- the API said: ${created:-${detail:-unknown}}"
        exit 1
    fi
done

mkdir -p "$(dirname "${OUT_FILE}")"
# Written atomically. The app container reads this file at start, and a
# partially written one would export an id with no secret -- which fails at
# the token endpoint rather than at start, several minutes and one sign-in
# attempt later.
tmp="${OUT_FILE}.partial"
{
    echo "AGENT_OIDC_CLIENT_ID='${client_id}'"
    echo "AGENT_OIDC_CLIENT_SECRET='${client_secret}'"
} > "${tmp}"
mv "${tmp}" "${OUT_FILE}"

log "wrote ${OUT_FILE} for client ${client_id}"
