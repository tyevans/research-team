# Settings and providers: the HTTP contract

Reference for `research_team/interfaces/web/settings.py`. W-C1 builds the
console's settings page against these shapes on a separate branch, so they are
a contract rather than an implementation detail: change one and the UI branch
finds out by breaking. `tests/interfaces/test_settings_routes.py` asserts the
field names; this file says what they mean.

## What a setting is

A setting is declared once, in `research_team/domain/settings.py`, and resolved
against a scope chain. Resolution walks **project → user → tenant →
environment → built-in default** and stops at the first layer holding a value.
Every read reports which layer answered.

The environment is a layer, not a legacy: a deployment configured entirely by
`AGENT_*` keeps working with no settings database at all, and
`infrastructure/config.py` reads exactly the bottom two layers.

A setting's key is mechanically its environment variable minus `AGENT_`,
lowercased. `AGENT_EXTRACTION_CHUNK_SIZE` is `extraction_chunk_size`. Nothing
maps between the two by hand.

## Scopes

| scope | id | who sets it |
|---|---|---|
| `project` | project uuid | most settings |
| `user` | user id (W-A's subject) | most settings |
| `tenant` | tenant id | everything, including the deployment-only settings |

Each declaration names the scopes it accepts. A write to a scope the
declaration excludes is a **422**, not a silently ignored row: a pgvector DSN
is tenant-only because a project override would point every project's vectors
at another database.

**Nothing on this surface is authorized yet.** Scope ids are explicit path and
query parameters and any caller may name any of them. W-A owns identity and
**W-B is the branch that adds the check** — every route carries a note saying
where it goes.

## Routes

### `GET /api/settings/schema`

Static; needs no store, no scope and no credentials. Answers on a build with
nothing wired.

```json
{
  "groups": [
    {
      "name": "Models",
      "settings": [
        {
          "key": "model",
          "env_var": "AGENT_MODEL",
          "type": "string",
          "label": "Chat model",
          "description": "The model the research agent talks to.",
          "group": "Models",
          "secret": false,
          "default": "qwen3.6-27b-mtp",
          "choices": [],
          "minimum": null,
          "maximum": null,
          "required_when": null,
          "scopes": ["project", "tenant", "user"]
        }
      ]
    }
  ],
  "scopes": ["project", "user", "tenant"],
  "roles": [{"role": "research", "setting_key": "model"}]
}
```

- `type` is one of `string`, `integer`, `number`, `boolean`, `enum`.
- `choices` is non-empty exactly when `type` is `enum`.
- `minimum`/`maximum` apply to `integer` and `number` and are enforced on write.
- `required_when` is prose for help text — the condition under which leaving it
  unset is a failure. It is not enforced by the write route; the reader raises
  at the point of use, where it can name the feature that needed it.
- **`default` is `null` for every secret**, always. The schema never carries a
  credential, including a placeholder one.
- `scopes` is sorted alphabetically, not in resolution order. `scopes` at the
  top level is the resolution order.
- Groups appear in registry order, which is the order the form should render.

### `GET /api/settings/resolved?project=&user=&tenant=`

All three parameters are optional; supply the ones the caller has. The chain is
reordered into resolution order server-side, so a query string that lists them
differently resolves identically.

```json
{
  "scope_chain": [{"scope": "project", "scope_id": "p1"}],
  "settings": [
    {"key": "model", "value": "my-model", "layer": "project", "scope_id": "p1", "secret": false},
    {"key": "extraction_chunk_size", "value": 2000, "layer": "default", "scope_id": null, "secret": false},
    {
      "key": "api_key",
      "value": null,
      "layer": "project",
      "scope_id": "p1",
      "secret": true,
      "masked": {"present": true, "last_four": "1234", "display": "set (…1234)"}
    }
  ]
}
```

- `value` is typed: a `boolean` setting comes back as `true`/`false`, an
  `integer` as a number.
- `layer` is one of `project`, `user`, `tenant`, `environment`, `default`. It
  is what lets a form distinguish "this project overrides it" from "this is the
  default", which want different controls.
- `scope_id` is `null` unless a scope supplied the value.
- **`value` is `null` for every secret**, whether or not one is stored, and a
  `masked` object appears instead. `last_four` is `null` for a secret shorter
  than eight characters. The ciphertext never appears either.

### `PUT /api/settings/{scope}/{scope_id}/{key}`

```json
{"value": "my-model"}
```

`value` is always a string, whatever the setting's type — a form posts strings,
and one parser is what keeps the HTTP layer and the environment layer agreeing
about what `"on"` means. Booleans accept `1/true/yes/on` and `0/false/no/off`,
case-insensitively; enums are lowercased.

- `200` `{"scope": "project", "scope_id": "p1", "key": "model", "stored": true}`
- `422` — unknown key, unknown scope, a value the declaration refuses, a scope
  the declaration forbids, or a secret with no `AGENT_SETTINGS_KEY` configured.
  `detail` says which.

A secret is encrypted before it reaches the store. There is no route that reads
one back.

### `DELETE /api/settings/{scope}/{scope_id}/{key}`

- `204` — the override was removed; the setting now resolves from the next layer.
- `404` — there was no override to remove. Deliberately not `204`: clearing a
  key that was never set is almost always a misspelled key, and a silent
  success is how the misspelling survives.
- `422` — unknown key or unknown scope.

### `GET /api/providers`

Static. Fifteen entries, no credentials of any kind.

```json
{
  "providers": [
    {
      "id": "openai",
      "display_name": "OpenAI",
      "base_url": "https://api.openai.com/v1/",
      "auth": "bearer",
      "openai_compatible": true,
      "capabilities": ["chat", "embeddings", "tools", "vision"],
      "credentials": [
        {"name": "api_key", "label": "API key", "secret": true, "required": true, "setting_key": null}
      ],
      "notes": ""
    }
  ]
}
```

- `capabilities` is sorted, and is what the **provider** offers — not what a
  particular model does. A catalogue cannot know whether a given model has
  vision, and a picker should read it as "is an embedding role worth offering
  here at all".
- `auth` is `bearer`, `header_key`, `query_key`, `signed` or `none`.
- `openai_compatible` is `true` for eleven of the fifteen. The four that are
  not: `anthropic` (its own headers), `google` (native Gemini surface, key as a
  query parameter), `azure_openai` (per-deployment addressing) and `bedrock`
  (SigV4 signing).
- `base_url` may contain `{placeholders}` — Azure and Bedrock only. A form has
  to fill them in; a connection test against an unfilled url answers
  `unsupported`.

### `POST /api/providers/{provider_id}/test`

```json
{"api_key": "sk-...", "base_url": "https://optional-override/v1/"}
```

Both fields optional. The key is used once and **not stored** — a caller
testing a key it has already saved sends it again, because a route that read it
back out of the store would be a read path for a secret in all but name.

```json
{
  "provider_id": "openai",
  "outcome": "ok",
  "ok": true,
  "detail": "OpenAI answered 200",
  "models": ["gpt-4o-mini"],
  "latency_ms": 142
}
```

`outcome` is one of:

| outcome | meaning |
|---|---|
| `ok` | the endpoint answered and listed models |
| `unauthorized` | 401/403 — the credential was refused |
| `unreachable` | DNS, TLS, timeout, connection refused |
| `unsupported` | cannot be probed from a base url and a key — Bedrock, Azure, or a url with placeholders left in |
| `error` | any other 4xx/5xx |

- `models` is capped at 25 names.
- `detail` never contains the credential, including in the failure cases —
  Gemini carries the key in the query string, so the exception text is reduced
  to its type name rather than passed through.
- `404` for an unknown provider id; `503` when no probe is wired.

## Model profiles

`ModelProfile` (`domain/settings.py`) is a named
`(provider, model, credentials, parameters)` triple selectable per **role** —
`research`, `extraction`, `curation`, `embedding`, `vision`. The
`roles` array in the schema response maps each role to the setting its model
name resolves from today, which is what keeps profiles additive: a deployment
that defines none behaves exactly as it did, through the same reader.

A profile names a *credential setting key*; it never carries the credential.

Profiles have no storage route in W-C0. The concept, the roles and the
role → setting bridge are here; the per-scope selection UI and its persistence
are W-C1's.

## Secrets

- Stored AES-256-GCM encrypted, key from `AGENT_SETTINGS_KEY` (`openssl rand
  -base64 32`).
- With no key configured, reads still work through the environment layer and
  writes of a secret are refused, naming the variable. Nothing is ever stored
  in the clear.
- Rotating the key does not break the surface: an unreadable row falls through
  to the environment layer and the field reports `not set` rather than the page
  failing.
- Encryption at rest protects a stolen database file and a careless backup. It
  does not protect against a compromised host — anyone who can read the process
  environment can read the key.

## Environment-only variables

Seven variables are deliberately **not** settings, each with its reason in
`ENVIRONMENT_ONLY`:

| variable | why |
|---|---|
| `AGENT_DB` | the settings table lives in this database; a setting cannot decide where it is read from |
| `AGENT_INTERACTION_DB` | a path resolved before any store opens |
| `AGENT_BLOB_ROOT` | a filesystem path owned before a request exists; also the test suite's isolation hook |
| `AGENT_PERCEPTION_ROOT` | a filesystem path, same reason |
| `AGENT_WEB_HOST` | bound before the first request |
| `AGENT_WEB_PORT` | bound before the first request |
| `AGENT_SETTINGS_KEY` | storing it beside the ciphertext makes the encryption decorative |

`tests/domain/test_settings_registry.py` derives this population from the
source of the modules that read the environment, so an eighth variable fails at
collection unless it is either declared or excused with a sentence.
