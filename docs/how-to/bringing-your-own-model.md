# Bring your own model

This system talks to fifteen model providers. This page shows you how to pick
one, store a key for it, test that the key works, and select it for a role.

Every command below was run against a live server on 2026-08-29. The responses
are copied from that run, not composed.

## Before you start: which role you are choosing a model for

**A stored choice takes effect for extraction. It does not take effect for the
other four roles.** Read this before you pick a section, because the two halves
of this page do different jobs.

- **Extraction.** Sections 1 to 4 are enough. A profile selected for the
  extraction role, or an `extraction_model`, `base_url` and `api_key` written at
  project scope, is read by the next extraction run in that project. You do not
  restart, and you do not set an environment variable.
- **Research, curation, embedding and vision.** Section 5 is the only way. The
  clients for these four roles are built from `config.<key>()`, which reads the
  environment and then the built-in default. A scoped override for them is
  stored, reads back correctly, and changes nothing.

`research_team/application/effective.py` is the consuming half for extraction.
[`docs/configuration.md`](../configuration.md) lists the nine settings it covers
and states the rule that decides the question for any other key.

## 0. Start a server

```bash
cd frontend && npm run build    # once; the console is not served without it
uv run web.py
```

The API is at `http://127.0.0.1:8000`. Every example below uses that address.

If you only want the API, you can skip the frontend build. `/` answers 503
until you run it, but the routes under `/api` answer either way.

## 1. Pick a provider

List the catalogue:

```bash
curl -s http://127.0.0.1:8000/api/providers
```

Fifteen providers come back. These are the ids:

| Id | Provider | Needs a key | OpenAI-compatible |
|---|---|---|---|
| `openai` | OpenAI | yes | yes |
| `anthropic` | Anthropic | yes | no |
| `google` | Google Gemini | yes | no |
| `mistral` | Mistral | yes | yes |
| `groq` | Groq | yes | yes |
| `together` | Together AI | yes | yes |
| `fireworks` | Fireworks AI | yes | yes |
| `deepseek` | DeepSeek | yes | yes |
| `xai` | xAI | yes | yes |
| `openrouter` | OpenRouter | yes | yes |
| `ollama` | Ollama | no | yes |
| `lmstudio` | LM Studio | no | yes |
| `vllm` | vLLM | no | yes |
| `azure_openai` | Azure OpenAI | yes | no |
| `bedrock` | AWS Bedrock | yes | no |

Three of them run on your own machine and need no key: Ollama, LM Studio and
vLLM. They still declare an `api_key` credential, marked not required. A key
is sent if you set one.

Each entry also carries its default base URL, its capabilities, and a `notes`
field where the provider is unusual. Anthropic's note, for example:

> `x-api-key` plus a required `anthropic-version` header, and no embedding
> models. Probed with the same client and different headers.

**`openai_compatible: false` does not mean "unsupported".** It means the
request shape is not OpenAI's. The catalogue records the shape; the client
work that uses it is a later slice.

## 2. Test a key before you store it

`POST /api/providers/{id}/test` makes one live call to the provider and tells
you what happened. The key travels in the body, is used once, and is **not
stored**.

```bash
curl -s -X POST http://127.0.0.1:8000/api/providers/openai/test \
  -H 'content-type: application/json' \
  -d '{"api_key": "sk-your-key-here"}'
```

There are five outcomes. All five below were produced by a real run:

**`ok`** — the provider answered, and you get up to 25 model names back:

```json
{"provider_id":"vllm","outcome":"ok","ok":true,
 "detail":"vLLM answered 200",
 "models":["gemma-4-26b-qat","muse-glimmer-30b","qwen3-embedding-0.6b"],
 "latency_ms":24}
```

**`unauthorized`** — the endpoint is there and rejected the credential:

```json
{"provider_id":"openai","outcome":"unauthorized","ok":false,
 "detail":"OpenAI refused the credential (401)","models":[],"latency_ms":161}
```

**`unreachable`** — nothing answered:

```json
{"provider_id":"ollama","outcome":"unreachable","ok":false,
 "detail":"ConnectError reaching Ollama","models":[],"latency_ms":null}
```

**`unsupported`** — the provider cannot be probed this way, and the reply says
why:

```json
{"provider_id":"bedrock","outcome":"unsupported","ok":false,
 "detail":"Bedrock signs requests with SigV4 rather than carrying a token, so a key alone cannot be tested from here."}
```

```json
{"provider_id":"azure_openai","outcome":"unsupported","ok":false,
 "detail":"Azure OpenAI is addressed per deployment and offers no model list to probe."}
```

**`error`** — the endpoint answered with something else at or above 400.

Two limits worth knowing. The probe times out at 10 seconds. And an
`unreachable` reply names only the exception type, never the URL, because
Gemini carries the key in the query string and a URL in an error message is a
key in a log file.

### Testing a local server

Point the probe at your own address with `base_url`:

```bash
curl -s -X POST http://127.0.0.1:8000/api/providers/vllm/test \
  -H 'content-type: application/json' \
  -d '{"base_url": "http://192.168.1.14:8080/v1/"}'
```

## 3. Store the key

Secrets are encrypted at rest. **Set `AGENT_SETTINGS_KEY` before you start the
server**, or a write to a secret setting is refused:

```
{"detail":"AGENT_SETTINGS_KEY is not set, so secrets cannot be stored"}
```

Generate one and restart:

```bash
export AGENT_SETTINGS_KEY=$(openssl rand -base64 32)
uv run web.py
```

Then write the key. Scope it to a project, a user or a tenant:

```bash
curl -s -X PUT http://127.0.0.1:8000/api/settings/project/demo/provider_key.groq.api_key \
  -H 'content-type: application/json' \
  -d '{"value": "gsk_abcdefgh12345678"}'
```

```json
{"scope":"project","scope_id":"demo","key":"provider_key.groq.api_key","stored":true}
```

**Every value is a string on the wire**, whatever its declared type. `{"value":
9}` is rejected; `{"value": "9"}` is accepted and parsed to the integer 9.

For a provider with one credential you may leave the credential name off.
`provider_key.openai` normalises to `provider_key.openai.api_key`.

For Azure OpenAI and Bedrock you may not, and the refusal names the choices:

```
{"detail":"Azure OpenAI declares 4 credentials (api_key, resource, deployment,
api_version); name one, e.g. provider_key.azure_openai.api_key"}
```

Azure needs four: `api_key`, `resource`, `deployment`, `api_version`. Bedrock
needs three: `access_key_id`, `secret_access_key`, `region`. The addresses
among those — Azure's resource, deployment and api_version, and Bedrock's
region — are stored in the clear, because hiding an address buys nothing.

### Reading it back

You cannot read a secret back. That is structural, not a rule a route
remembers. Ask for the resolved settings and you get a mask:

```bash
curl -s 'http://127.0.0.1:8000/api/settings/resolved?project=demo'
```

```json
{"key": "provider_key.groq.api_key", "value": null, "layer": "project",
 "scope_id": "demo", "secret": true,
 "masked": {"present": true, "last_four": "5678", "display": "set (…5678)"}}
```

The mask shows the **last** four characters. A prefix would identify the
vendor rather than the key.

### Removing it

```bash
curl -s -X DELETE http://127.0.0.1:8000/api/settings/project/demo/provider_key.groq.api_key
```

204 when it was there. 404 when it was not.

## 4. Select a model for a role

There are five roles, and each has its own setting:

| Role | Setting | What it does |
|---|---|---|
| `research` | `model` | The agent you talk to |
| `extraction` | `extraction_model` | Pulls entities and relationships out of documents |
| `curation` | `curation_model` | Phrases media searches and judges the results |
| `embedding` | `embedding_model` | Turns text into vectors. Tenant scope only — see below |
| `vision` | `vision_model` | Describes frames and images |

**`embedding_model` refuses a project or user override with a 422.** Its width,
`embedding_dimension`, is baked into a vector store the whole process shares, so
two projects that disagree raise `DimensionMismatchError` on the first write. A
profile selected for the embedding role at tenant scope is still only a record;
the client is built from the environment.

**The five are independent, and that is recent.** Extraction used to resolve
from `model`, so choosing a cheap extraction model silently repointed the
research agent. Five roles whose keys collide are four roles.
`test_no_two_roles_resolve_from_one_setting` holds them apart.

A **model profile** names a provider, a model, and the setting that holds the
credential. It does not carry the secret itself: a structure that could hold a
key is a structure that will eventually be logged with one in it.

Define one:

```bash
curl -s -X PUT http://127.0.0.1:8000/api/profiles/project/demo/fast \
  -H 'content-type: application/json' \
  -d '{"provider_id": "groq",
       "model": "llama-3.3-70b-versatile",
       "credential_key": "provider_key.groq.api_key"}'
```

```json
{"scope":"project","scope_id":"demo","name":"fast","stored":true}
```

Select it for a role:

```bash
curl -s -X PUT http://127.0.0.1:8000/api/profiles/project/demo/roles/extraction \
  -H 'content-type: application/json' -d '{"profile": "fast"}'
```

Read the result:

```bash
curl -s 'http://127.0.0.1:8000/api/profiles?project=demo'
```

```json
{"role":"extraction","model":"llama-3.3-70b-versatile","layer":"project",
 "scope_id":"demo","setting_key":"extraction_model","profile":"fast","dangling":null}
```

Four things about this surface:

- **`credential_key` must name a secret setting.** Pointing it at an ordinary
  one is refused.
- **Profiles and selections resolve separately.** A project may select a
  profile a *tenant* defined. That is the ordinary case for a shared team
  credential.
- **A selection does not require the profile to exist.** It is resolved when
  read. If nothing in the chain defines the name, the role reads back with
  `dangling` set to that name rather than silently falling back.
- **Deleting a profile does not clear the selections that use it.** They go
  dangling. That is reported rather than hidden, because a role that quietly
  reverted to the default is a role you find out about from your bill.

A role with no profile reads its own setting. A role whose setting is empty
falls back to the chat model, and says so with `layer: "fallback"`.

**Only the extraction role's selection reaches a run.** `open_graph` asks
`EffectiveSettings.extraction` for the project it is opening, and that call is
what reads the profile: its model, its `base_url` and the secret its
`credential_key` names all replace the settings underneath, together. The other
four roles report their selection on this surface and build their clients from
the environment. Verified on 2026-08-29 against a live endpoint: selecting a
profile for `extraction` made the endpoint report the profile's model name in
its error, where the same project had reported `extraction_model`'s value a run
earlier.

**A profile with no `base_url` of its own leaves the endpoint alone.** The
field is the profile's, not the catalogue's, and it is optional. Give it a value
when the profile names a hosted provider. Leave it out when the endpoint belongs
to the deployment rather than to the choice of model.

## 5. Make it take effect for the other four roles

Set the environment variables and restart. This is the only layer the research,
curation, embedding and vision clients read.

Skip this section if you are configuring **extraction** only. Step 4 already
made that choice take effect, and an environment variable set here is the layer
underneath it: the project override wins for extraction either way.

For a hosted OpenAI-compatible provider — Groq here — the chat endpoint is
three variables:

```bash
export AGENT_BASE_URL=https://api.groq.com/openai/v1/
export AGENT_MODEL=llama-3.3-70b-versatile
export AGENT_API_KEY=gsk_your_key_here
uv run web.py
```

Take the base URL from the catalogue entry in step 1.

To point *only* extraction somewhere cheap, and leave the research agent where
it is:

```bash
export AGENT_EXTRACTION_MODEL=llama-3.1-8b-instant
```

Every provider credential also has a variable, synthesised from the catalogue:

```bash
export AGENT_PROVIDER_KEY_GROQ_API_KEY=gsk_...
export AGENT_PROVIDER_KEY_BEDROCK_REGION=us-east-1
```

The pattern is `AGENT_PROVIDER_KEY_<PROVIDER>_<CREDENTIAL>`, uppercased.

### Two things to check on a hosted endpoint

**Lower the extraction concurrency.** `AGENT_EXTRACTION_CONCURRENCY` defaults
to 8, which matches a local server's slot count. Against a per-minute quota
that is a rate-limit error partway through an ingest:

```bash
export AGENT_EXTRACTION_CONCURRENCY=2
```

The bound is per *document*. Two documents ingested at once are two ceilings.

**Leave `AGENT_EXTRACTION_THINKING` off.** It is off by default. OpenAI's
hosted API rejects the field with a 400 on the first extraction call.

### Embeddings are a separate endpoint

`AGENT_EMBEDDING_MODEL` is not `AGENT_MODEL`. If your chat provider serves no
embedding models — Anthropic does not — point embeddings elsewhere:

```bash
export AGENT_EMBEDDING_BASE_URL=http://localhost:8081/v1/
export AGENT_EMBEDDING_MODEL=nomic-embed-text
export AGENT_EMBEDDING_DIMENSION=768
```

The dimension is a property of the model, not a preference. Set it with the
model or the probe rejects the width.

If you get this wrong, nothing breaks loudly. The adapter probes once on the
first ingest, logs a warning, and consolidates on two features instead of
three for the rest of the process. Ingests still complete. Set
`AGENT_VECTOR_STORE=none` to skip the probe and say you meant it.

## Do not expose this

There is **no authorization on any of these routes**. Scope ids are plain path
parameters and nothing checks them. Anyone who can reach the HTTP surface can
write a tenant-scoped override.

`AGENT_WEB_HOST` defaults to `127.0.0.1`, so a default deployment is not
exposed. Keep it that way until the work in
[`docs/design/tenancy-and-authorization.md`](../design/tenancy-and-authorization.md)
lands.

Encryption at rest protects a stolen database file and a careless backup. It
does not protect against anyone who can read this process's environment,
because `AGENT_SETTINGS_KEY` is in it.

## Where to read more

| | |
|---|---|
| [`docs/reference/settings-api.md`](../reference/settings-api.md) | every route, request and response |
| [`docs/configuration.md`](../configuration.md) | all 41 settings, the five layers, and the costly defaults |
| [`docs/design/settings-page.md`](../design/settings-page.md) | the console surface these routes were designed for |
