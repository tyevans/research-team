# Master plan: users, tenancy, settings, and the console rework

Status: in progress, started 2026-08-29. This file is the shared reference for
every workstream below. Read it before starting one; it says what the other
workstreams own so two branches do not both redesign the same thing.

## The shape of the target system

The project today has no notion of a person. Every route names a project, every
project is global, and every knob is an `AGENT_*` environment variable read at
process start (`research_team/infrastructure/config.py`, ~60 of them). The
target has four new layers under that, in dependency order:

1. **Identity** — Zitadel as the OIDC provider, run locally under
   `docker-compose.auth.yml`. The app is a confidential OIDC client; a browser
   session is a signed cookie carrying the subject. A `User` read model mirrors
   the claims we care about, keyed by the Zitadel subject.
2. **Tenancy** — every project belongs to exactly one tenant (an "organisation"
   in Zitadel's vocabulary, and a Zitadel org is what backs it). Multi-tenancy
   is in from the first commit rather than ported in later: the tenant id is a
   column on every read model row and a field on the events that create things.
3. **Authorization** — role assignments on two subjects: tenant and project.
   Relationship-based (a Zanzibar-shaped tuple store), because the interesting
   question here is "can this user read this project" through group and tenant
   inheritance, and that is a graph walk, not a column lookup.
4. **Settings** — a scoped key/value store replacing the environment. Three
   scopes, resolved most-specific-first: `project` > `user` > `tenant` >
   built-in default. Includes bring-your-own-model provider credentials.

## Workstreams

Each is a branch, a PR, and one agent. `W-A` blocks `W-B` and `W-C1`; the rest
are independent and run in parallel.

- **W-A — identity foundation.** Zitadel compose file, OIDC login/logout/callback,
  session cookie, `CurrentUser` FastAPI dependency, `User` read model, sign-up
  flow, the login and account UI. Ships with auth *optional* (`AGENT_AUTH=off`
  keeps the current single-user behaviour) so the other branches keep passing.
- **W-B — tenancy and RBAC.** Tenant aggregate, project ownership, the tuple
  store and its checker, role assignment UI, and the permission decorator over
  every route.
- **W-C0 — settings domain and provider registry.** Scoped settings aggregate,
  resolution order, the provider catalogue (OpenAI, Anthropic, Google, Mistral,
  Groq, Together, Fireworks, DeepSeek, xAI, OpenRouter, Ollama, LM Studio,
  vLLM, Azure OpenAI, Bedrock), credential storage, and the migration of the
  `AGENT_*` variables into settings with the environment as the lowest layer.
- **W-C1 — project settings page.** The UI over W-C0, per-project overrides,
  model picker, connection tests.
- **W-D — the index page.** Complete redesign of the landing page and project
  list.
- **W-E — course authoring under load.** The authoring run crashes on a large
  topic; fix by managing context and using subagents properly.
- **W-F — the lesson slideshow.** A deck-style presentation view for a lesson,
  alongside the current document view.

## Rules that apply to every workstream

- The four gates in `CLAUDE.md` are the bar, and **CI is what runs them.** Do
  not run a full suite locally: it takes about ten minutes here against two on
  CI, several agents share this machine, and a loaded box produces failures
  that are not real (CLAUDE.md, "A failure under load is not evidence"). Run
  `uv run ruff check .` and `uv run ruff format --check .` -- cheap, repo-wide,
  and the gate most often missed -- plus the specific test files you touched,
  and then push. `npm run verify`'s full chain belongs to CI too; run the
  individual `vitest` files you wrote, one process at a time.
- `npm run test:browser` is still yours to run for anything whose correctness
  is a computed style or a measurement, narrowly, on the files you touched.
  jsdom lays nothing out, so there is no CI substitute for it -- it is outside
  `verify` and outside CI on purpose.
- Pre-release: break events, data and contracts rather than migrating. Say so
  in the docstring and update `tests/infrastructure/test_schema_evolution.py`.
- Every new port with exactly one adapter needs a test that drives both ends
  over real data. See CLAUDE.md, "Events".
- Open a PR when the gates pass. Do not merge your own; the orchestrator does.
