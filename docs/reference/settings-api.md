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

## Provider credentials: the `provider_key.` namespace

The registry declares four secrets, all for this project's own endpoints. The
catalogue enumerates fifteen providers. Bridging the two is a **dynamic key
namespace**, synthesised at request time from the catalogue rather than
declared:

```
provider_key.<provider_id>[.<credential>]
```

- `provider_key.groq` — a provider with exactly one credential may omit the
  trailing segment. It **normalises** to `provider_key.groq.api_key`, and every
  route reports the normalised form. The two spellings are one row; the key is
  hashed into the storage row id, so this is load-bearing rather than cosmetic.
- `provider_key.bedrock` — **422**. Bedrock declares three credentials
  (`access_key_id`, `secret_access_key`, `region`), so the segment is required
  and the error names all three. Guessing would silently store a secret access
  key under the id's name.
- `provider_key.evilcorp` — **422**. The provider id is validated against the
  catalogue, never accepted as free text: it lands in a storage key and a URL
  segment.
- `provider_key.groq.password` — **422**. The credential must be one the
  provider declares.

A dynamic key is a `SettingSpec` like any other. Parsing, scoping, encryption,
masking and the resolution walk are the same code path with no branch on the
key's shape — which is why a dynamic secret is covered by the same
`test_a_secret_never_leaves_a_read_endpoint` population rather than by a case
of its own.

**Secrecy comes from the credential, not from the prefix.** Azure's `resource`,
`deployment` and `api_version`, and Bedrock's `region`, are declared
`secret: false` in the catalogue: they are stored and read back in the clear,
because a region is not a secret.

Each one also answers to a synthesised environment variable —
`provider_key.groq.api_key` is `AGENT_PROVIDER_KEY_GROQ_API_KEY` — so a
container can configure a provider credential with no settings database. That
variable is in neither `SETTINGS` nor `ENVIRONMENT_ONLY`: it belongs to neither
population, because it does not exist until a provider id is named.

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
  "roles": [{"role": "research", "setting_key": "model"}],
  "provider_credential_group": "Provider credentials"
}
```

The `groups` array carries the declared settings **and** the twenty provider
credentials the catalogue implies, all as ordinary specs. The group they are
in is named by `provider_credential_group` rather than left for a client to
recognise by key prefix — a client matching on `"provider_key."` would be a
second, private copy of the key format.

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
  The provider-credential group is last.

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

- Every declared setting **and** every provider credential appears, whether or
  not one is stored. A form has to be able to show "not set" for a provider
  nobody has configured yet; listing only stored keys would mean it could never
  offer the first one.
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

`ModelProfile` is a named `(provider, model, credentials, parameters)` triple
selectable per **role**: `research`, `extraction`, `curation`, `embedding`,
`vision`. A profile names a *credential setting key*; it never carries the
credential, because a profile is read back to a browser whole.

**No two roles resolve from one setting.** Extraction used to map to `model`
alongside research, so choosing a cheap extraction model silently repointed the
research agent at it — five roles sharing four keys is four roles. Extraction
now has `extraction_model`, which falls back to the chat model when unset,
exactly as `curation_model` does.

Profiles and role selections are **two separate walks**. A project may select a
profile a *tenant* defined, which is the ordinary case for a shared team
credential; folding them together would force a project to redefine a profile
in order to use it. Profiles shadow by name (most specific definition wins);
selections resolve by role (most specific choice wins).

### `GET /api/profiles?project=&user=&tenant=`

```json
{
  "scope_chain": [{"scope": "project", "scope_id": "p1"}],
  "profiles": [
    {
      "scope": "tenant",
      "scope_id": "t1",
      "name": "groq-fast",
      "provider_id": "groq",
      "model": "llama-3.3-70b-versatile",
      "credential_key": "provider_key.groq.api_key",
      "base_url": null,
      "parameters": {"temperature": 0}
    }
  ],
  "roles": [
    {
      "role": "extraction",
      "model": "llama-3.3-70b-versatile",
      "layer": "project",
      "scope_id": "p1",
      "setting_key": "extraction_model",
      "profile": "groq-fast",
      "dangling": null
    }
  ]
}
```

One endpoint rather than two, because the interesting question is the pair: a
list of profiles says nothing about which is in use, and a list of roles with
only names in it cannot be rendered without the definitions.

- `model` is always populated. A role always has a model, because the settings
  layer underneath always answers; a caller that only wants to make a call
  reads this field and ignores the rest.
- `layer` is the selecting scope when a profile answered, otherwise the layer
  the role's *setting* resolved from, or `fallback` when the role's setting is
  unset and the chat model answered.
- `setting_key` is reported even when a profile answered — it is what the form
  offers as the way back.
- **`dangling`** names a selected profile that no scope in the chain defines.
  Reported rather than silently ignored: a role quietly repointed at the
  default model is the exact failure this feature exists to prevent. The
  fallback still happens, because something has to be called.
- A name defined at two scopes appears once, as the more specific one.

### `PUT /api/profiles/{scope}/{scope_id}/{name}`

```json
{
  "provider_id": "groq",
  "model": "llama-3.3-70b-versatile",
  "credential_key": "provider_key.groq",
  "base_url": null,
  "parameters": {"temperature": 0}
}
```

`parameters` is an open dict, because it is provider-specific (`temperature`,
`top_p`, Anthropic's `thinking`, vLLM's `chat_template_kwargs`) and a catalogue
cannot enumerate what fifteen providers accept. It is stored and handed back
whole; nothing interprets it.

- `200` `{"scope", "scope_id", "name", "stored": true}`
- `422` — unknown provider, empty model or name, or a `credential_key` that is
  not a **secret** setting. A profile's credential is what a call is
  authenticated with; pointing it at an ordinary setting would put a non-secret
  on the credential path and render a secret-shaped field that is not one.

### `DELETE /api/profiles/{scope}/{scope_id}/{name}`

`204`, or `404` when this scope defined no profile by that name.

A role still selecting the deleted name is **left selecting it** and reads back
as `dangling`. Cascading was rejected: a more specific scope may define the same
name, in which case the selection is still correct, and a delete that silently
unpicked a role would be a second, invisible write.

### `PUT /api/profiles/{scope}/{scope_id}/roles/{role}`

```json
{"profile": "groq-fast"}
```

`200`, or `422` for a role outside the five. The profile need not exist yet — a
selection is resolved against the chain at read time, so a tenant may select a
name a project will define.

### `DELETE /api/profiles/{scope}/{scope_id}/roles/{role}`

`204`, or `404` when the role was never selected at that scope. The role falls
back to its setting.

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
