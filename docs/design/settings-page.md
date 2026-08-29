# The settings page, and the bring-your-own-model surface

Design for **W-C1**. It stands on the contract W-C0 landed in
`docs/reference/settings-api.md`, `research_team/domain/settings.py` and
`research_team/domain/providers.py`. Read that reference first: this document
argues about presentation and says almost nothing the API does not already
carry, which is deliberate — `settings.py`'s own docstring says the registry
exists so that a settings UI does not become a second, hand-written
description of the same forty knobs. Every number, label, group, bound and
choice on this page is rendered from `GET /api/settings/schema`. None of them
is typed into the frontend.

Nothing here is implementation. It is written to be executed from, once W-C0
and W-A merge.

## 0. What the contract already decides for us

Four facts do most of the design work, and each of them removes an option that
would otherwise look attractive.

**Resolution reports its own provenance.** Every row of
`GET /api/settings/resolved` carries `layer` and `scope_id`. The page never has
to infer where a value came from, and must never try — a provenance label
derived from a second walk is a label that can disagree with the first.

**The scope chain is a query parameter, and every parameter is optional.** So
"what would this fall back to if I cleared the override" is answerable with a
second call to the same route with the current scope omitted. No new endpoint,
and — importantly — it is the *only* correct answer for a secret, whose
`default` is `null` in the schema by design.

**Writes are per key.** `PUT /api/settings/{scope}/{scope_id}/{key}` takes one
value. There is no batch. A page built around a "Save all" button would be
thirty-nine requests with a partial-failure story nobody can render; the
contract is already shaped for per-field commit, and we should take the shape
it offers rather than build a form over it.

**`scopes` on each declaration decides what is even on the page.** Fourteen of
the thirty-nine settings are tenant-only, and they are not scattered: the
`Stores`, `Media` and `Observability` groups are tenant-only *in full*. A
project settings page is therefore twenty-five settings in six groups, not
thirty-nine in nine, and three of the scariest groups — the ones holding a
pgvector DSN and a Neo4j password — never render for the person the page is
for. Most of section 2's problem is solved before we write any code, by
filtering on `spec.scopes` and rendering no empty group.

Counts in this paragraph are as of the registry today. They are stated to make
the argument concrete; the page derives them and a test never asserts them.

## 1. Making a layered value legible

This is the design problem. A page where nobody can tell whether they changed
anything is the failure mode, and it is easy to ship because every wrong
version of it looks fine on a fresh database where every value is a default.

### The row

A setting is a **row**, not a form field. Left to right:

```
▍ Chat model            [ qwen3.6-27b-mtp            ]  project  Clear
│                       clearing this falls back to `llama-3.3-70b` (tenant)
```

- **A 2px bar on the leading edge**, coloured by layer. Accent when this scope
  set it; hairline when it was inherited; nothing drawn for `default`.
- **The control**, typed from the schema (section 2).
- **A layer chip** carrying the *word* — `project`, `user`, `tenant`, `env`,
  `default`. The bar is redundant with the chip on purpose. Colour alone fails
  for a colourblind reader, and this repository has already paid twice for
  believing a colour was carrying a meaning.
- **`Clear`**, present only when `layer` equals the scope being edited.
  `DELETE` answers 404 when there is no override, and the contract says why —
  clearing a key that was never set is almost always a misspelling. A button
  that can only ever produce that 404 should not be on screen.
- **The fallback line**, under an overridden row only: what clearing would
  reveal, and which layer would answer.

### Where the fallback line comes from

One extra query for the whole page, not one per row: `GET
/api/settings/resolved` with the current scope's parameter omitted. The
response is the same shape, so a row's fallback is a lookup by key in a second
map. It is correct for secrets (which report `masked` rather than a value) and
correct when a *higher* layer answers, which is where the obvious alternative
fails.

**Rejected: computing the fallback from the schema's `default`.** It is free
and it is wrong whenever a user, tenant or environment layer sits between the
project and the default — which is the whole reason the feature exists. It is
also `null` for every secret, always, so the one field where "what happens if I
clear this" is frightening is the one field it cannot answer.

### The whole chain, on demand

Clicking the layer chip opens a `Popover` listing every layer with what it
holds, greyed for the layers that did not answer. This is the "explain this
value" affordance and it is the only place the full chain belongs.

**Rejected: rendering the chain inline on every row.** It is accurate and
unreadable — five lines times twenty-five rows, with twenty-two of them saying
"default" three times. The chain is the answer to a question people ask about
one setting at a time.

### Overrides as a filter, not as the page

A toolbar toggle, **"Overridden here (n)"**, filters to rows this scope set.

**Rejected: making that the default view.** A page showing only differences
cannot answer "what is this project actually using", which is the more common
question and the one somebody arrives with after a bad extraction run. It is a
good second view and a bad first one.

### Editing an inherited row

The control is **live, not locked**. Typing into an inherited row and
committing creates the override; the bar turns accent, the chip changes, the
fallback line appears, and `Clear` arrives. That transition is the page's main
feedback that something happened.

**Rejected: a per-row "Override" toggle that unlocks the control.** Two clicks
for the common case, and the toggle's state is a second thing that can disagree
with the data — a row that reads `tenant` with the toggle on is a state
somebody has to define.

## 2. Thirty-nine settings without thirty-nine dares

In order of how much each one buys:

**Scope filtering**, as above. Free, and it removes three groups.

**Groups as sections, in registry order.** The contract states groups arrive in
the order the form should render, so the frontend sorts nothing. A sticky rail
of group names on the left scrolls the page. Not tabs: this page should be one
scannable document that browser find works over, because "which knob was it"
is how people actually arrive.

**Search**, matching label, key, description **and `env_var`**. The env var is
the load-bearing one — operators come to this page from `AGENT_EXTRACTION_
CHUNK_SIZE` in a compose file, and a search that cannot find it sends them back
to the shell. A hit auto-expands its group.

**Collapsed groups, not an "advanced" tier.** Groups after the first two render
folded; expansion is remembered in the existing `PreferenceStore`; a group
containing an override or a search hit always opens.

**Rejected: an advanced/basic split.** The registry carries no such flag, and
inventing one in the frontend is exactly the thing `settings.py` exists to
prevent — a second hand-written description of forty settings, which drifts on
the first commit that adds a fortieth. If a tier is wanted it is a field on
`SettingSpec`, on the W-C0 surface, where the declaration lives and a test can
hold it.

**A summary above the fold.** Not a settings group: the five roles and the
models answering them, plus each configured provider's last connection result.
Most visits are about three settings, and all three are in that block.

### The controls, from the schema

| `type` | control | notes |
|---|---|---|
| `string` | `<input>` `.input` | `<textarea>` for nothing today |
| `integer`, `number` | `<input type="number">` | `min`/`max` from the schema, mirrored in the message |
| `boolean` | `Choices` (on/off) | posts `"on"`/`"off"` — the spelling `serialise` uses |
| `enum` | `<select>` from `choices` | already lowercase; nothing to normalise |

Client validation is **derived from the declaration, never written down**:
`minimum`, `maximum` and `choices` come off the schema. Booleans are the one
place a temptation exists — `TRUE_WORDS` and `FALSE_WORDS` are Python
constants that the schema does not publish — so the client never parses a
boolean. It offers two controls and posts `on` or `off`, which is a subset the
server is guaranteed to accept. The server stays the authority in every case;
client validation exists to stop a round trip, not to be the rule.

`required_when` renders as help text under the field, in the same tone as
`description`. The contract says it is prose and unenforced; presenting it as a
validation rule would make the page assert something the server does not.

## 3. Providers and roles

The feature the user asked for. It is the top section of the page, above the
settings groups, and it is two blocks.

### Connections

One card per provider the person has configured, plus an **Add connection**
picker over the fifteen from `GET /api/providers`. A card carries:

- display name, `base_url`, and the capability chips as **the provider's**
  capabilities. The contract is explicit that a catalogue cannot know whether a
  given model has vision; the chips answer "is an embedding role worth
  offering here at all" and the tooltip says so.
- the credential fields the provider declares, each rendered by section 4's
  secret field. Bedrock declares three; nothing about the card assumes one.
- `base_url` **placeholder fields**. Azure and Bedrock carry `{resource}`,
  `{deployment}` and `{region}` markers. The card parses them out and renders
  one field each. `Test` stays disabled until they are filled — and an unfilled
  url answers `unsupported` anyway, which is the honest second line of defence
  rather than the only one.
- a **Test** button, and the outcome as a badge: `ok` with latency, or
  `unauthorized` / `unreachable` / `unsupported` / `error` with `detail`. The
  five outcomes get five distinct sentences, because "it didn't work" over a
  wrong key and over a firewall sends people to different places.

**Test is not validation; it is how the model picker gets filled.** The
response carries up to twenty-five model names. That is the argument for giving
the test a real button on a card instead of a row in a table: it is the step
that turns an empty picker into a list. Where no list is available — Bedrock,
Azure, `unsupported` — the model field falls back to free text, with the
outcome's `detail` as the explanation for why.

The key sent to `POST /api/providers/{id}/test` is the one **currently typed**,
before saving. Test-then-save puts the common failure (a mistyped key) before
storage rather than after it. For an already-saved key the field is empty and
the person re-pastes, which the contract requires and which the button's help
text states plainly rather than leaving as a surprise.

### Roles

Five rows — research, extraction, curation, embedding, vision — each a
provider picker and a model picker. Providers lacking `embeddings` do not
appear for the embedding role; likewise `vision`.

**Two things must be visible here, and both are consequences of
`ROLE_MODEL_KEYS`.**

First, **research and extraction resolve from the same setting**, `model`.
Today, choosing a cheap local model for extraction silently repoints the
research agent. The two rows are drawn joined, with one line saying they share
`model`, and changing either shows what the other becomes before the commit.
Hiding this would produce the worst kind of settings bug: the user changed one
thing and two things moved.

Second, **the row says which setting it writes**, in mono, small. It is the
bridge that keeps profiles additive, and it is what makes the roles block and
the `Models` group below it obviously the same data rather than two competing
truths.

### The gap this section runs into, and the ask it makes of W-C0

`ModelProfile.credential_key` names a *secret setting key*. The registry
declares exactly four secret keys — `api_key`, `embedding_api_key`,
`pgvector_dsn`, `neo4j_password` — and `PUT` answers 422 for an unknown key.
So **there is today no key to store a Groq credential in**, and
"bring-your-own-model over fifteen providers" cannot be persisted against the
contract as it stands. Profiles also have no storage route; the reference says
so and assigns persistence to W-C1.

The smallest change that closes both, proposed rather than assumed:

- a **dynamic secret key namespace**, `provider_key.<provider_id>` and
  `provider_key.<provider_id>.<credential_name>` for the multi-credential
  providers, synthesised as a secret `SettingSpec` at request time by a
  `dynamic_spec_for()` beside `spec_for()`. Parsing, scoping, encryption and
  masking are then unchanged, and the schema route keeps listing only the
  static declarations — the providers route already tells a form which
  credentials to ask for, so nothing needs a second catalogue.
- **profile storage** on the same table under a reserved key per role, written
  through the same `PUT`.

This is a change to W-C0's surface, so it is slice S4a below and it needs the
W-C0 owner's agreement before S4 starts. It is called out here because
discovering it during implementation would stall the one slice the user cares
most about.

## 4. Secrets

The field has exactly three states and no fourth.

**Unset.** An empty `<input type="password">`, placeholder `paste a key`. Help
text carries `masked.display`, which is `not set`.

**Set, untouched.** No input element with a value in it at all — the display is
text, `set (…1234)`, beside `Replace` and `Clear`. There is deliberately no
row of bullets: a bullet string is a *value*, it can be submitted, and it is
one careless change away from being round-tripped back to the server as the
literal password.

**Replacing.** An empty password input, plus `Cancel` returning to
set-and-untouched. Component state is `''` until the person types. The value is
never seeded from anything.

`autoComplete="off"` and `data-1p-ignore` on every secret input. A masked
display that looks like a filled password field is an invitation to a password
manager, and a manager filling it is precisely the round trip the contract
forbids.

**Clear means fall back, not "no credential".** The confirm says which:
"The project will use the tenant's key (…9f21)" — text from the second
resolved query of section 1. Where the fallback is `not set` the confirm says
that instead, because clearing into nothing is the case worth a moment's
pause.

**A failed save keeps the paste.** Concretely, and these are the assertions:
commit is per field, so one 422 cannot discard a neighbouring good value; the
field's state is not cleared, reset or refetched on failure; the error renders
beside the field with the server's `detail`; and a navigation away with unsaved
text in any secret field prompts. The 422 that will actually happen most is
"a secret with no `AGENT_SETTINGS_KEY` configured", which is a deployment
problem the person cannot fix from this page — so it gets its own sentence
naming the variable, not a generic validation message.

## 5. Where the page lives

**A top-level route**, not a project facet:

```
#/settings/project/<project-id>
#/settings/user/<subject>
#/settings/tenant/<tenant-id>
```

parsing to `{ name: 'settings', scope, scopeId, group }`, with `group`
optional so a link can land on a section.

The argument is `routes.ts`'s own, already made for the interaction log: a
facet forces a project id onto a view, and the first thing a reader of a
user-scope settings page would have to do is pick a project to ignore. The same
reasoning gives the same answer. Reached from a control in the project header
(carrying the current project's id) and, once W-A ships an account menu, from
there for the user scope.

### One component, parametrised by scope — where it holds and where it breaks

`SettingsPage({ scope, scopeId })` is right for the settings list, the search,
the grouping and the secret field. It breaks in three places, each small and
each needing a per-scope value rather than a per-scope component:

1. **The chain below is different.** A tenant page has only `environment` and
   `default` beneath it, so its layer-chip vocabulary is shorter and its
   fallback line is usually "the built-in default". A `scopeChain` derived from
   `RESOLUTION_ORDER` handles it; nothing branches.
2. **Which settings render is `spec.scopes`.** Twenty-five at project,
   thirty-nine at tenant. Already the filter; no extra work.
3. **The roles and providers block means something different at tenant
   scope** — it is the deployment default rather than one project's choice.
   Same component, different copy.

So: one component, one `SCOPE_COPY` record of three entries, and no third page.

## 6. States

**Loading.** `schema` and `providers` are static and need no scope — cache them
with `staleTime: Infinity`. Only `resolved` is per-scope, so after the first
visit the page frame paints immediately and one region fills in.

**Schema fine, resolved failing.** This is the read-model trap from CLAUDE.md
arriving as a UI question, and it will happen the first time a column is added
against an existing database. The page must render the form **disabled with an
`ErrorBox` naming the failure**, never an empty page: an empty settings page
reads as "this project has no settings", which is a wrong answer rather than an
absent one.

**Empty.** No providers configured yet — the Connections block shows a
first-run card ("connect a provider to choose models per role"), not an empty
list.

**Permission denied.** W-B has not shipped, and the resolved response carries
no capability field. The seam is one function:

```
canEdit(key: string): boolean   // default () => true
```

with 403 from a `PUT` as a first-class outcome that flips the row read-only and
explains why. When W-B lands a capability, it fills that function and the
component does not change.

The trap to design around here is the one CLAUDE.md names under the interaction
log: a permissive default makes "never wired up" and "working" identical to a
test. So the test for this is not "nothing threw" — it drives the page with a
`canEdit` that answers **no** and asserts the row is read-only and the control
is absent from the tab order.

## 7. Two repository traps, specifically

**Form controls and the cascade.** This page is the largest concentration of
`<input>`, `<select>` and `<button>` in the console. The bare-control rules in
`tokens.css` are in `@layer base` today, so utilities on them win — that fight
is over. What is not over is the next unlayered rule: if this page needs a
stylesheet, **defaults go in `@layer base` and decisions go in a named class**,
and no element selector is written outside a layer. Two concrete follow-ons:

- extend `control-defaults.browser.test.tsx`, whose three cases all render a
  `<button>`, to cover `<select>` and `<input>` — this page is the first screen
  where a `<select>` carrying utilities is load-bearing.
- the provenance bar is a **directional border**, which is the other entry in
  that section: a directional width alone is correct and draws; `border-solid`
  beside it draws three unwanted sides; and `border-0 border` on the row
  container would be two width utilities fighting in the stylesheet's sort
  order. The row wants `border-l-2` and nothing else.

**jsdom judges none of this.** Roles, focus order, keyboard routing, the
masked field never holding a value, and the per-field commit calls all belong
in `*.test.tsx`. These belong in `*.browser.test.tsx` and nowhere else:

- the provenance bar paints in the layer's colour (an unlayered `.chip-*` rule
  can still beat a utility, which is how this class of bug shipped twice);
- the sticky group rail's offset under the console header;
- the row focus ring is not clipped — use `.lay-ring-inward`, not a
  `focus-visible:outline-offset-*` utility, which the global unlayered
  `:focus-visible` beats silently;
- `elementFromPoint` over a row's `Clear` control, because rows carry a hover
  treatment and a stretched click target painting over its own children is the
  exact `CourseCard` defect.

## 8. Slices

Five, ordered, each independently mergeable. Each states what it is done
against — the slice before it, not the whole page.

### S1 — the page tells the truth, and writes nothing

Read-only. Schema, providers and resolved fetched; groups, rows, layer chips,
the chain popover, search, scope filter, and every empty/loading/error state.

- `frontend/src/domain/settings/` — `spec.ts`, `layer.ts` (types only)
- `frontend/src/application/ports/repositories.ts` — `SettingsRepository`
- `frontend/src/infrastructure/http/settings-repository.ts` (+ test)
- `frontend/src/infrastructure/http/mappers.ts`, `dto.ts`
- `frontend/src/application/queries/keys.ts`
- `frontend/src/presentation/routing/routes.ts` (+ `routes.test.ts`)
- `frontend/src/presentation/settings/SettingsPage.tsx`, `SettingRow.tsx`,
  `LayerChip.tsx`, `GroupRail.tsx` (+ tests, + stories)
- `frontend/src/app/App.tsx`, `container.ts`, `container-context.tsx`

### S2 — writing and clearing an override

Per-field commit, typed controls from the schema, `Clear`, the fallback line
from the second resolved query, 422 rendering, optimistic update and rollback.
Non-secret settings only.

- `frontend/src/presentation/settings/SettingControl.tsx`, `ClearOverride.tsx`
- `frontend/src/presentation/settings/use-setting-commit.ts`
- `frontend/src/infrastructure/http/settings-repository.ts` (put, delete)
- `frontend/src/presentation/settings/settings-row.browser.test.tsx`
- `frontend/src/styles/control-defaults.browser.test.tsx` (select and input)

### S3 — secrets

The three-state field, replace, cancel, clear-with-fallback confirm, paste
preservation on failure, the unsaved-secret leave guard.

- `frontend/src/presentation/settings/SecretField.tsx` (+ test, + story)
- `frontend/src/presentation/settings/use-unsaved-guard.ts`
- `frontend/src/presentation/settings/secret-field.browser.test.tsx`

### S4a — the backend the roles block needs *(W-C0 surface; agree first)*

Dynamic `provider_key.*` secret specs and per-role profile persistence, as
section 3 sets out. Not W-C1's code, but W-C1's blocker.

- `research_team/domain/settings.py` (`dynamic_spec_for`)
- `research_team/interfaces/web/settings.py`
- `docs/reference/settings-api.md`
- `tests/domain/test_settings_registry.py`,
  `tests/interfaces/test_settings_routes.py`

### S4 — providers and roles

Connection cards, credential fields, `{placeholder}` fields, the test button
and its five outcomes, model pickers filled from the test, the five role rows,
capability gating, and the shared-`model` warning.

- `frontend/src/domain/settings/provider.ts`, `role.ts`
- `frontend/src/infrastructure/http/providers-repository.ts` (+ test)
- `frontend/src/presentation/settings/ConnectionCard.tsx`,
  `ProviderPicker.tsx`, `RoleRow.tsx`, `RolesBlock.tsx`, `TestOutcome.tsx`
  (+ tests, + stories)

### S5 — the other two scopes, and the permission seam

`#/settings/user/…` and `#/settings/tenant/…`, `SCOPE_COPY`, the `canEdit`
seam and its denied states, and the entry points from the project header and
the account menu.

- `frontend/src/presentation/routing/routes.ts`
- `frontend/src/presentation/settings/scope-copy.ts`
- `frontend/src/presentation/settings/permissions.ts`
- `frontend/src/presentation/settings/SettingsPage.tsx`
- `frontend/src/app/App.tsx`

## 9. What this design is most likely to be wrong about

The fallback line costs a second `resolved` request and adds a line under every
overridden row. If most projects override two settings, it is nearly free and
clearly worth it. If a project overrides twenty, the page grows a second column
of small grey text that people learn to ignore, and the honest answer is to
move it into the chain popover and leave the row with the chip alone. That is a
one-component change and worth revisiting after the first real page is on
screen — from a screenshot, not from reasoning.
